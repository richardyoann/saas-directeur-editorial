import copy
import datetime
import os
from pathlib import Path
import tempfile
import unittest
from scripts.arvor_ci_evidence import GATES, seal, verify, validate_report, key_bytes

SHA = "a" * 40
KEY = b"k" * 48

def example():
    return {
        "schema": "arvor-local-ci-v1", "repository": "richardyoann/saas-directeur-editorial",
        "sha": SHA, "base_sha": "b" * 40, "run_id": "test-run-abcdef1234",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "environment": "isolated-no-secrets", "human_review": "required", "deployment": "not_performed",
        "gates": {name: {"status": "passed", "exit_code": 0,
                         "tests": 1 if name in {"regression_312", "regression_314", "browser"} else 0,
                         "skipped": 0} for name in GATES},
    }

class EvidenceTests(unittest.TestCase):
    def test_valid(self):
        report = example()
        self.assertTrue(validate_report(report, SHA))
        self.assertTrue(verify(seal(report, SHA, KEY), SHA, KEY))

    def test_sha_tampering(self):
        signed = seal(example(), SHA, KEY)
        signed["report"]["sha"] = "b" * 40
        with self.assertRaises(ValueError): verify(signed, SHA, KEY)

    def test_required_gate_missing(self):
        report = example()
        report["gates"].pop("secret_scan")
        with self.assertRaises(ValueError): seal(report, SHA, KEY)

    def test_no_tests_and_skips_fail(self):
        report = example()
        report["gates"]["regression_312"]["tests"] = 0
        with self.assertRaises(ValueError): seal(report, SHA, KEY)
        report = example()
        report["gates"]["browser"]["skipped"] = 1
        with self.assertRaises(ValueError): seal(report, SHA, KEY)

    def test_failure_sealed_but_not_accepted(self):
        report = example()
        report["gates"]["video_75"] = {"status": "failed", "exit_code": 1, "tests": 0, "skipped": 0}
        self.assertFalse(verify(seal(report, SHA, KEY), SHA, KEY))

    def test_stale_and_no_approval(self):
        report = example()
        report["created_at"] = "2020-01-01T00:00:00Z"
        with self.assertRaises(ValueError): seal(report, SHA, KEY)
        report = example()
        report["human_review"] = "approved"
        with self.assertRaises(ValueError): seal(report, SHA, KEY)

    def test_private_key_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "key"
            file.write_bytes(KEY)
            os.chmod(file, 0o644)
            with self.assertRaises(ValueError): key_bytes(file)
            os.chmod(file, 0o600)
            self.assertEqual(key_bytes(file), KEY)

if __name__ == "__main__": unittest.main()
