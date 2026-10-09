import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts import install_project_capabilities as installer


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        shutil.copytree(installer.ROOT / "skills", self.root / "skills")
        shutil.copytree(installer.ROOT / "agents", self.root / "agents")
        shutil.copy2(installer.ROOT / installer.LOCK, self.root / installer.LOCK)
        self.package = installer.validate(self.root)

    def test_repository_lock_matches_current_sources(self):
        package = installer.validate(installer.ROOT)
        self.assertGreater(len(package["skills"]), 0)
        self.assertGreater(len(package["agents"]), 0)

    def test_activation_adds_links_and_preserves_configuration(self):
        config = self.root / ".codex/config.toml"
        config.parent.mkdir()
        config.write_text('existing = "preserved"\n')
        original = config.read_bytes()
        report = installer.activate(self.root, self.package)
        self.assertTrue(report["activated"])
        self.assertEqual(len(report["created"]), len(self.package["skills"]) + len(self.package["agents"]))
        for source, destination in installer.targets(self.root, self.package):
            self.assertTrue(destination.is_symlink())
            self.assertEqual(destination.resolve(), source.resolve())
        self.assertEqual(config.read_bytes(), original)
        second = installer.activate(self.root, self.package)
        self.assertTrue(second["activated"])
        self.assertEqual(second["created"], [])

    def test_conflict_preserves_existing_file_and_creates_no_partial_links(self):
        destinations = installer.targets(self.root, self.package)
        conflict = destinations[-1][1]
        conflict.parent.mkdir(parents=True)
        conflict.write_text("User configuration to preserve")
        report = installer.activate(self.root, self.package)
        self.assertFalse(report["activated"])
        self.assertEqual(report["created"], [])
        self.assertEqual(conflict.read_text(), "User configuration to preserve")
        self.assertTrue(report["blockers"])
        for _, destination in destinations[:-1]:
            self.assertFalse(destination.exists())
            self.assertFalse(destination.is_symlink())

    def test_changed_skill_is_rejected_without_rewriting_lock(self):
        skill = next((self.root / "skills").glob("*/SKILL.md"))
        original_lock = (self.root / installer.LOCK).read_bytes()
        skill.write_text(skill.read_text() + "\nChanged instructions.\n")
        with self.assertRaises(ValueError):
            installer.validate(self.root)
        self.assertEqual((self.root / installer.LOCK).read_bytes(), original_lock)

    def test_source_parent_symlink_is_rejected_before_activation(self):
        external = self.root.parent / (self.root.name + "-source")
        shutil.move(self.root / "agents", external)
        self.addCleanup(shutil.rmtree, external)
        (self.root / "agents").symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            installer.validate(self.root)
        report = installer.activate(self.root, self.package)
        self.assertFalse(report["activated"])
        self.assertEqual(report["created"], [])

    def test_invalid_package_does_not_create_empty_lock(self):
        empty = self.root / "invalid"
        empty.mkdir()
        with patch.object(installer, "ROOT", empty):
            self.assertEqual(installer.main(["--lock"]), 1)
        self.assertFalse((empty / installer.LOCK).exists())

    def test_activation_reports_partial_failure_without_removing_links(self):
        original = Path.symlink_to
        calls = []
        def create_link(path, *args, **kwargs):
            calls.append(path)
            if len(calls) == 2:
                raise PermissionError("Synthetic filesystem failure")
            return original(path, *args, **kwargs)
        with patch.object(Path, "symlink_to", create_link):
            report = installer.activate(self.root, self.package)
        self.assertFalse(report["activated"])
        self.assertTrue(report["partial"])
        self.assertEqual(len(report["created"]), 1)
        self.assertTrue((self.root / report["created"][0]).is_symlink())

    def test_parent_symlink_outside_repository_is_blocked(self):
        external = self.root.parent / (self.root.name + "-external")
        external.mkdir()
        self.addCleanup(shutil.rmtree, external)
        (self.root / ".agents").symlink_to(external, target_is_directory=True)
        report = installer.activate(self.root, self.package)
        self.assertFalse(report["activated"])
        self.assertEqual(report["created"], [])
        self.assertEqual(list(external.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
