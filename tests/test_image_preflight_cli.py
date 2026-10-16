"""Exercise the documented command from outside the project directory."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ImagePreflightCliTests(unittest.TestCase):
    def test_direct_script_returns_json_without_project_on_pythonpath(self):
        script = Path(__file__).resolve().parents[1] / "scripts/diagnose_image_runtime.py"
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            # Preserve installed test dependencies, but exclude the project root.
            root = str(script.parents[1])
            environment["PYTHONPATH"] = os.pathsep.join(
                part for part in environment.get("PYTHONPATH", "").split(os.pathsep)
                if part and str(Path(part).resolve()) != root
            )
            result = subprocess.run(
                [sys.executable, str(script), "--url", "https://example.org"],
                cwd=directory, env=environment, capture_output=True, text=True,
                timeout=15,
            )
        self.assertEqual(result.returncode, 2, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason"], "invalid_or_public_image_url")
        self.assertFalse(payload["ready"])
        self.assertFalse(payload["gpu_verified"])
        self.assertFalse(payload["generation_verified"])
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
