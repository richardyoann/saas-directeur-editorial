import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import install_external_skills as external


class ExternalSkillsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = {"namespace": "example", "repo": "owner/repository", "ref": "main",
                       "selectors": [{"name": "example-skill"}]}
        self.package = {"schema_version": 1, "sources": [self.source]}
        self.save_registry()
        self.helper = self.root / "official-helper.py"
        self.helper.write_text("raise RuntimeError('Never execute this test fixture')\n")
        self.sha = "a" * 40

    def save_registry(self):
        (self.root / external.REGISTRY).write_text(json.dumps(self.package))

    def simulate_install(self, command, **kwargs):
        destination = Path(command[command.index("--dest") + 1]) / command[command.index("--name") + 1]
        destination.mkdir()
        (destination / "SKILL.md").write_text("---\nname: example-skill\ndescription: Test fixture\n---\n# Example skill\n")
        (destination / "LICENSE").write_text("Preserved upstream license\n")
        (destination / "references").mkdir()
        (destination / "references/guide.md").write_text("Reference material\n")
        return subprocess.CompletedProcess(command, 0, "", "")

    def test_default_plan_and_check_use_no_network_or_writes(self):
        original = set(self.root.rglob("*"))
        with patch.object(external, "ROOT", self.root), patch.object(external, "fetch_json") as fetch, \
                patch.object(external.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(external.main([]), 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "pending")
            self.assertEqual(external.check(self.root)["status"], "pending")
            fetch.assert_not_called()
            run.assert_not_called()
        self.assertEqual(set(self.root.rglob("*")), original)

    def test_discovery_matches_single_segment_globs_and_dependencies(self):
        source = {"selectors": [{"glob": "skills/*/SKILL.md"}]}
        found = external.select_skills(source, ["skills/alpha/SKILL.md", "skills/nested/deep/SKILL.md"])
        self.assertEqual(found, [{"name": "alpha", "path": "skills/alpha"}])
        source = {"selectors": [{"name": "grill-me"}, {"name": "grilling", "dependency_of": "grill-me"}]}
        found = external.select_skills(source, ["skills/productivity/grill-me/SKILL.md", "skills/shared/grilling/SKILL.md"])
        self.assertEqual({item["name"] for item in found}, {"grill-me", "grilling"})
        self.assertEqual(external.select_skills({"selectors": [{"path": ".", "name": "handoff"}]},
                                                ["SKILL.md"]), [{"name": "handoff", "path": "."}])

    def test_unsafe_source_path_and_ref_are_rejected(self):
        for changes in ({"ref": "../../main"}, {"ref": "--exec"}, {"repo": "https://host/repo"},
                        {"selectors": [{"path": "../outside", "name": "example-skill"}]}):
            with self.subTest(changes=changes):
                self.package["sources"] = [{**self.source, **changes}]
                self.save_registry()
                with self.assertRaises(ValueError):
                    external.registry(self.root)
        with self.assertRaises(ValueError):
            external.select_skills({"selectors": [{"name": "example-skill"}]}, ["../example-skill/SKILL.md"])

    def test_resolver_pins_sha_and_rejects_truncated_tree(self):
        with patch.object(external, "fetch_json", side_effect=[{"sha": self.sha},
                         {"tree": [{"path": "skills/example-skill/SKILL.md", "type": "blob"}]}]) as fetch:
            sha, skills = external.resolve(self.source)
            self.assertEqual(sha, self.sha)
            self.assertEqual(skills[0]["path"], "skills/example-skill")
            self.assertIn(self.sha + "?recursive=1", fetch.call_args_list[1].args[0])
        with patch.object(external, "fetch_json", side_effect=[{"sha": self.sha}, {"truncated": True}]):
            with self.assertRaises(ValueError):
                external.resolve(self.source)

    def test_apply_pins_helper_preserves_files_and_skips_matching_receipt(self):
        with patch.object(external, "resolve", return_value=(self.sha, [{"name": "example-skill", "path": "skills/example-skill"}])), \
                patch.object(external.subprocess, "run", side_effect=self.simulate_install) as run:
            results = external.apply(self.root, self.helper)
            self.assertEqual(results[0]["status"], "installed")
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--ref") + 1], self.sha)
            self.assertEqual(command[command.index("--method") + 1], "download")
            self.assertEqual(command[1], str(self.helper))
            self.assertEqual(external.check(self.root)["status"], "installed")
            again = external.apply(self.root, self.helper)
            self.assertEqual(again[0]["status"], "skipped")
            self.assertEqual(run.call_count, 1)
        receipts = external.load_receipts(self.root)
        self.assertEqual(len(receipts), 2)
        self.assertIn("LICENSE", {item["path"] for item in receipts[0]["files"]})
        self.assertIn("references/guide.md", {item["path"] for item in receipts[0]["files"]})

    def test_existing_without_receipt_is_preserved_without_subprocess(self):
        destination = self.root / "vendor/skills/example/example-skill"
        destination.mkdir(parents=True)
        (destination / "SKILL.md").write_text("Local existing content")
        with patch.object(external, "resolve", return_value=(self.sha, [{"name": "example-skill", "path": "skills/example-skill"}])), \
                patch.object(external.subprocess, "run") as run:
            results = external.apply(self.root, self.helper)
        run.assert_not_called()
        self.assertEqual(results[0]["status"], "conflict")
        self.assertEqual((destination / "SKILL.md").read_text(), "Local existing content")

    def test_destination_symlink_is_refused_without_touching_target(self):
        target = self.root / "outside"
        target.mkdir()
        (self.root / "vendor").symlink_to(target, target_is_directory=True)
        with patch.object(external, "resolve", return_value=(self.sha, [{"name": "example-skill", "path": "skills/example-skill"}])), \
                patch.object(external.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                external.apply(self.root, self.helper)
        run.assert_not_called()
        self.assertEqual(list(target.iterdir()), [])

    def test_modified_install_fails_check_and_is_not_overwritten(self):
        with patch.object(external, "resolve", return_value=(self.sha, [{"name": "example-skill", "path": "skills/example-skill"}])), \
                patch.object(external.subprocess, "run", side_effect=self.simulate_install):
            external.apply(self.root, self.helper)
        path = self.root / "vendor/skills/example/example-skill/SKILL.md"
        path.write_text("Local modification")
        with self.assertRaises(ValueError):
            external.check(self.root)
        with patch.object(external, "resolve", return_value=(self.sha, [{"name": "example-skill", "path": "skills/example-skill"}])), \
                patch.object(external.subprocess, "run") as run:
            self.assertEqual(external.apply(self.root, self.helper)[0]["status"], "conflict")
        run.assert_not_called()
        self.assertEqual(path.read_text(), "Local modification")

    def test_timeout_and_resolution_failures_have_blocked_receipts(self):
        with patch.object(external, "resolve", side_effect=TimeoutError("network timeout")):
            results = external.apply(self.root, self.helper)
        self.assertEqual(results[0]["status"], "blocked")
        self.assertEqual(results[0]["scope"], "source_resolution")
        with patch.object(external, "resolve", return_value=(self.sha, [{"name": "example-skill", "path": "skills/example-skill"}])), \
                patch.object(external.subprocess, "run", side_effect=subprocess.TimeoutExpired("helper", 60)):
            results = external.apply(self.root, self.helper)
        self.assertEqual(results[0]["status"], "blocked")
        self.assertEqual(len(external.load_receipts(self.root)), 2)
        self.assertEqual(external.check(self.root)["status"], "pending")

    def test_activation_requires_complete_install_and_preserves_conflicts(self):
        self.assertFalse(external.activate(self.root)["activated"])
        with patch.object(external, "resolve", return_value=(self.sha, [{"name": "example-skill", "path": "skills/example-skill"}])), \
                patch.object(external.subprocess, "run", side_effect=self.simulate_install):
            external.apply(self.root, self.helper)
        destination = self.root / ".agents/skills/example-skill"
        destination.parent.mkdir(parents=True)
        destination.write_text("Existing native instructions")
        report = external.activate(self.root)
        self.assertFalse(report["activated"])
        self.assertEqual(report["created"], [])
        self.assertEqual(destination.read_text(), "Existing native instructions")

    def test_activation_creates_verified_native_link_and_is_idempotent(self):
        with patch.object(external, "resolve", return_value=(self.sha, [{"name": "example-skill", "path": "skills/example-skill"}])), \
                patch.object(external.subprocess, "run", side_effect=self.simulate_install):
            external.apply(self.root, self.helper)
        report = external.activate(self.root)
        self.assertTrue(report["activated"])
        destination = self.root / ".agents/skills/example-skill"
        self.assertEqual(destination.resolve(), (self.root / "vendor/skills/example/example-skill").resolve())
        self.assertEqual(external.activate(self.root)["created"], [])

    def test_partial_glob_collection_is_not_reported_complete(self):
        self.package["sources"][0]["selectors"] = [{"glob": "skills/*/SKILL.md"}]
        self.save_registry()
        calls = []
        def install_one(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                return self.simulate_install(command, **kwargs)
            return subprocess.CompletedProcess(command, 1, "", "failure")
        with patch.object(external, "resolve", return_value=(self.sha, [
                {"name": "example-skill", "path": "skills/example-skill"},
                {"name": "second-skill", "path": "skills/second-skill"}])), \
                patch.object(external.subprocess, "run", side_effect=install_one):
            external.apply(self.root, self.helper)
        self.assertEqual(external.check(self.root)["status"], "partial")

    def test_new_sha_conflicts_and_incomplete_selection_reports_partial(self):
        with patch.object(external, "resolve", return_value=(self.sha, [{"name": "example-skill", "path": "skills/example-skill"}])), \
                patch.object(external.subprocess, "run", side_effect=self.simulate_install):
            external.apply(self.root, self.helper)
        self.package["sources"][0]["selectors"].append({"name": "another-skill"})
        self.save_registry()
        self.assertEqual(external.check(self.root)["status"], "partial")
        with patch.object(external, "resolve", return_value=("b" * 40, [{"name": "example-skill", "path": "skills/example-skill"}])), \
                patch.object(external.subprocess, "run") as run:
            results = external.apply(self.root, self.helper)
        self.assertEqual(results[0]["status"], "conflict")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
