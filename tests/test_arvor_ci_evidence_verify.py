"""Negative-path coverage of the trusted read-only evidence consistency check."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts.arvor_ci_evidence_verify import verify_receipt
from scripts.arvor_local_ci import GATES

SHA = "a" * 40
BASE = "b" * 40


class EvidenceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.evidence = self.root / "evidence"
        self.checkout = self.root / "candidate"
        self.evidence.mkdir()
        self.checkout.mkdir()
        run_id = str(uuid4())
        gates = []
        for name in GATES:
            counts = None
            if name.startswith("regression_"):
                counts = {"tests": 390, "failures": 0, "errors": 0, "skipped": 0}
                contents = "Ran 390 tests in 1s\n\nOK\n" + json.dumps(counts) + "\n"
            elif name == "browser":
                counts = {"tests": 18, "failures": 0, "errors": 0, "skipped": 0}
                contents = "Ran 18 tests in 1s\n\nOK\n"
            elif name == "video_75":
                contents = json.dumps({"verified": True, "synthetic": True,
                    "video_duration_seconds": 75, "resolution": "720x1280",
                    "ffprobe": "passed", "data_mutation": False}) + "\n"
            else:
                contents = "OK\n"
            (self.evidence / (run_id + "-" + name + ".log")).write_text(contents, encoding="utf-8")
            gates.append({"name": name, "passed": True, "returncode": 0,
                "tests": counts, "log_sha256": hashlib.sha256(contents.encode()).hexdigest()})
        now = datetime.now(timezone.utc)
        self.report = {"schema": "arvor-local-ci-v1", "run_id": run_id,
            "repo": "richardyoann/saas-directeur-editorial", "pr": 214,
            "sha": SHA, "base_sha": BASE, "started_at": (now - timedelta(minutes=1)).isoformat(),
            "finished_at": now.isoformat(), "source": "isolated-local-tests",
            "status": "success", "gates": gates}
        self.receipt = self.evidence / (run_id + ".json")
        self.save()

    def save(self):
        self.receipt.write_text(json.dumps(self.report), encoding="utf-8")

    def run_verification(self):
        with patch("scripts.arvor_ci_evidence_verify.git", side_effect=[SHA, "", BASE]), \
             patch("scripts.arvor_ci_evidence_verify.subprocess.run",
                   return_value=SimpleNamespace(returncode=0)):
            return verify_receipt(self.receipt, self.evidence, self.checkout,
                                  SHA, BASE, 214)

    def test_sign_cli_refuses_signature_without_independent_log_check(self):
        from scripts.arvor_ci_attestation import main as attest_main
        with patch("sys.argv", ["attestation", "sign",
                                 "--input", str(self.receipt),
                                 "--key", str(self.root / "missing-private.key"),
                                 "--key-id", "ci-v1",
                                 "--output", str(self.root / "signed.json")]):
            with self.assertRaises(SystemExit) as error:
                attest_main()
        self.assertEqual(error.exception.code, 2)
        self.assertFalse((self.root / "signed.json").exists())

    def test_consistent_receipt_and_sixteen_logs(self):
        result = self.run_verification()
        self.assertEqual(result["verified_logs"], 16)
        self.assertFalse(result["attestation_signed"])
        self.assertFalse(result["independent_execution_provenance_verified"])

    def test_changed_log_rejected(self):
        (self.evidence / (self.report["run_id"] + "-browser.log")).write_text("FAIL\n")
        with self.assertRaisesRegex(ValueError, "digest"):
            self.run_verification()

    def test_absent_log_rejected(self):
        (self.evidence / (self.report["run_id"] + "-dependencies.log")).unlink()
        with self.assertRaises(FileNotFoundError):
            self.run_verification()

    def test_report_identity_mismatch_rejected(self):
        with patch("scripts.arvor_ci_evidence_verify.git", side_effect=[SHA, "", BASE]), \
             patch("scripts.arvor_ci_evidence_verify.subprocess.run",
                   return_value=SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(ValueError, "receipt identity"):
                verify_receipt(self.receipt, self.evidence, self.checkout,
                               SHA, BASE, 215)

    def test_symlink_log_rejected(self):
        log_file = self.evidence / (self.report["run_id"] + "-browser.log")
        other = self.root / "original"
        log_file.rename(other)
        log_file.symlink_to(other)
        with self.assertRaises(OSError):
            self.run_verification()

    def test_forged_video_success_with_matching_hash_rejected(self):
        log_file = self.evidence / (self.report["run_id"] + "-video_75.log")
        payload = json.dumps({"verified": True, "synthetic": True,
            "video_duration_seconds": 74, "resolution": "720x1280",
            "ffprobe": "passed", "data_mutation": False}) + "\n"
        log_file.write_text(payload)
        self.report["gates"][-1]["log_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
        self.save()
        with self.assertRaisesRegex(ValueError, "Video proof"):
            self.run_verification()


if __name__ == "__main__":
    unittest.main()
