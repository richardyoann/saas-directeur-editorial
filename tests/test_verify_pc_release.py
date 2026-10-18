"""Synthetic, read-only attestation tests; do not claim these test the real PC."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from scripts.verify_pc_release import verify
from scripts.verify_pc_release import probe_loopback


class PCReleaseEvidenceTests(unittest.TestCase):
    def test_studio_status_probe_does_not_reject_large_html(self):
        response = MagicMock(status=200)
        response.read.return_value = b'x' * 8193
        with patch('scripts.verify_pc_release.http.client.HTTPConnection') as connection:
            connection.return_value.getresponse.return_value = response
            self.assertEqual(probe_loopback('/studio', 8000), (200, None))
        response.read.assert_not_called()
        connection.return_value.close.assert_called_once()

    def test_health_json_remains_bounded(self):
        response = MagicMock(status=200)
        response.read.return_value = b'x' * 8193
        with patch('scripts.verify_pc_release.http.client.HTTPConnection') as connection:
            connection.return_value.getresponse.return_value = response
            with self.assertRaisesRegex(ValueError, 'http_response_too_large'):
                probe_loopback('/health', 8000)
        connection.return_value.close.assert_called_once()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.sha = "a" * 40
        self.release = self.root / "releases" / (self.sha + "-123")
        self.release.mkdir(parents=True)
        (self.root / "current").symlink_to(self.release, target_is_directory=True)
        (self.root / "last_delivery.json").write_text(json.dumps({
            "sha": self.sha, "regression": "passed", "candidate_live": "passed",
            "installed_live": "passed", "real_editorial_workflow": "passed",
            "database_migration": "test_database_only", "production_editorial_probe": "read_only"}))
        self.proc = self.root / "proc"
        (self.proc / "123").mkdir(parents=True)
        (self.proc / "123" / "cwd").symlink_to(self.release, target_is_directory=True)
        self.service = {"ActiveState": "active", "MainPID": "123",
                        "WorkingDirectory": str(self.root / "current")}
        self.responses = {"/health": (200, {"status": "ok"}),
                          "/ready": (200, {"ready": True}), "/studio": (200, None)}

    def check(self):
        return verify(self.root, self.sha, proc_root=self.proc,
                      service_reader=lambda: self.service,
                      probe=lambda path, port: self.responses[path])

    def test_full_proof_succeeds_without_writes(self):
        self.assertTrue(self.check()["verified"])
        self.assertTrue((self.root / "last_delivery.json").is_file())

    def test_rejects_other_sha_and_forged_receipt(self):
        with self.assertRaisesRegex(ValueError, "active_release_sha_mismatch"):
            verify(self.root, "b" * 40, proc_root=self.proc,
                   service_reader=lambda: self.service)
        receipt = json.loads((self.root / "last_delivery.json").read_text())
        receipt["installed_live"] = "failed"
        (self.root / "last_delivery.json").write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError, "delivery_receipt_does_not_prove_success"):
            self.check()

    def test_rejects_release_outside_managed_root(self):
        other = self.root / "unmanaged" / (self.sha + "-123")
        other.mkdir(parents=True)
        (self.root / "current").unlink()
        (self.root / "current").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "active_release_sha_mismatch"):
            self.check()

    def test_rejects_wrong_process_even_when_receipt_is_green(self):
        other = self.root / "unexpected"
        other.mkdir()
        (self.proc / "123" / "cwd").unlink()
        (self.proc / "123" / "cwd").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "api_process_not_running_expected_release"):
            self.check()

    def test_rejects_inactive_service(self):
        self.service["ActiveState"] = "inactive"
        with self.assertRaisesRegex(ValueError, "api_service_identity_invalid"):
            self.check()

    def test_rejects_readiness_failure(self):
        self.responses["/ready"] = (503, {"ready": False})
        with self.assertRaisesRegex(ValueError, "http_release_probe_failed"):
            self.check()

    def test_rejects_unreadable_process_or_untrusted_receipt_symlink(self):
        (self.proc / "123" / "cwd").unlink()
        with self.assertRaisesRegex(ValueError, "api_process_identity_unavailable"):
            self.check()
        receipt = self.root / "last_delivery.json"
        backup = self.root / "backup.json"
        receipt.rename(backup)
        receipt.symlink_to(backup)
        with self.assertRaisesRegex(ValueError, "delivery_receipt_missing_or_unsafe"):
            self.check()


if __name__ == "__main__":
    unittest.main()
