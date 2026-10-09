import subprocess
import unittest
from unittest.mock import patch

from scripts import diagnose_project


class DiagnoseTests(unittest.TestCase):
    def test_probe_handles_unavailable_commands_and_timeout(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("probe", 15)):
            with self.subTest(error=type(error).__name__), \
                    patch.object(diagnose_project.subprocess, "run", side_effect=error):
                self.assertFalse(diagnose_project.probe(["missing-command"]))

    def test_probe_does_not_print_secret_output(self):
        result = subprocess.CompletedProcess([], 1, "private credential", "private credential")
        with patch.object(diagnose_project.subprocess, "run", return_value=result), \
                patch("builtins.print") as output:
            self.assertFalse(diagnose_project.probe(["gh", "auth", "status"]))
            output.assert_not_called()
