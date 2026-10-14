"""Private runtime diagnosis never modifies services or reveals secrets."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.diagnose_runtime import config_info, diagnose, release_info


class RuntimeDiagnosisTests(unittest.TestCase):
    def test_missing_release_is_explicit_not_a_fake_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            result = release_info(root, "f" * 40)
            self.assertFalse(result["root_present"])
            self.assertFalse(result["receipt_present"])
            self.assertFalse(result["expected_sha_matches"])
            self.assertFalse(result["release_receipt_consistent"])

    def test_release_sha_receipt_and_config_presence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            release = root / "releases" / ("a" * 40 + "-123")
            release.mkdir(parents=True)
            (root / "current").symlink_to(release, target_is_directory=True)
            (root / "last_delivery.json").write_text(json.dumps({"sha": "a" * 40,
                                                                   "installed_live": "passed"}))
            (release / ".env").write_text(
                "EDITORIAL_ASYNC_ENABLED=true\nEDITORIAL_WEB_PASSWORD=private-secret-do-not-show\n")
            self.assertTrue(release_info(root, "a" * 40)["expected_sha_matches"])
            self.assertFalse(release_info(root, "b" * 40)["expected_sha_matches"])
            cfg = config_info(root)
            self.assertTrue(cfg["async_enabled"])
            self.assertTrue(cfg["configured"]["EDITORIAL_WEB_PASSWORD"])
            self.assertNotIn("private-secret-do-not-show", json.dumps(cfg))

    def test_diagnose_uses_only_get_probes_and_sanitized_services(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.diagnose_runtime.service_info",
                       return_value={"ActiveState": "inactive"}), patch(
                       "scripts.diagnose_runtime.http_info",
                       return_value={"/health": 200, "/ready": 503, "/studio": 404}):
                result = diagnose(Path(directory), 8000, "a" * 40)
            self.assertEqual(result["http_status"]["/ready"], 503)
            self.assertEqual(result["api_service"]["ActiveState"], "inactive")
            self.assertFalse(result["release"]["expected_sha_matches"])


if __name__ == "__main__":
    unittest.main()
