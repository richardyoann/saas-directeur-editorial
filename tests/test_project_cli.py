import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import project


class ProjectCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.patch = patch.object(project, "REPOSITORY", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.memory = self.root / "docs/memory"

    def run_cli(self, *arguments):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return project.main(list(arguments))

    def test_context_is_private_and_refuses_symlink(self):
        self.assertEqual(self.run_cli("start", "DEV-CLI", "--objective", "Reprise privée"), 0)
        self.assertEqual(self.run_cli("context", "--write-current"), 0)
        current = self.memory / "CURRENT.md"
        self.assertEqual(current.stat().st_mode & 0o777, 0o600)
        self.assertIn("DEV-CLI", current.read_text())
        other = self.root / "external.txt"
        other.write_text("Existing user document")
        # Only remove the generated temporary fixture, never repository data.
        current.unlink()
        current.symlink_to(other)
        self.assertEqual(self.run_cli("context", "--write-current"), 1)
        self.assertEqual(other.read_text(), "Existing user document")

    def test_invalid_data_does_not_create_event(self):
        self.run_cli("start", "DEV-CLI", "--objective", "Valider les interactions")
        self.assertEqual(self.run_cli("record", "DEV-CLI", "--kind", "decision",
                                     "--summary", "Invalid", "--data-json", "[]"), 1)
        from workflows.memory import MemoryStore
        self.assertEqual(MemoryStore(self.memory).verify(), 1)


if __name__ == "__main__":
    unittest.main()
