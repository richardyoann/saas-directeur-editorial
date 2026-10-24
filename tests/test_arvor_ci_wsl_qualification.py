"""Guardrails for the one-command WSL qualification helper (no Docker required)."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qualify_arvor_ci_wsl.sh"


class WslQualificationScriptTests(unittest.TestCase):
    def test_bash_syntax(self):
        proc = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_invalid_sha_blocks_before_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = subprocess.run(
                ["bash", str(SCRIPT), "bad-sha", "b" * 40, "c" * 40],
                env={**os.environ, "ARVOR_CI_LAB_DIR": temp},
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("controller SHA incomplet", proc.stderr)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_missing_lab_blocks_before_docker(self):
        with tempfile.TemporaryDirectory() as temp:
            absent = Path(temp) / "absent"
            proc = subprocess.run(
                ["bash", str(SCRIPT), "a" * 40, "b" * 40, "c" * 40],
                env={**os.environ, "ARVOR_CI_LAB_DIR": str(absent)},
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("lab absent", proc.stderr)
            self.assertFalse(absent.exists())

    def test_script_has_no_delivery_or_merge_command(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "git reset --hard", "git switch", "git push", "gh pr merge",
            "scripts/deploy_local.py", "docker compose down",
            "LOCAL_PC_ENABLED=", "LOCAL_PC_APPROVED_SHA=",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn("arvor_ci_evidence_verify", source)
        self.assertIn("SECURITY_AUDIT_REFRESH", source)
        self.assertIn("independante certifiee: NON", source)


if __name__ == "__main__":
    unittest.main()
