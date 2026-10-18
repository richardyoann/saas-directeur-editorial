"""Contract tests for local deterministic quality evidence."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.local_quality_gate import REQUIRED, assert_receipt, validate_test_database

SHA = "a" * 40


class LocalQualityReceiptTests(unittest.TestCase):
    def test_exact_sha_and_run_required(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            receipt = temp / ("arvor-quality-" + SHA + ".json")
            receipt.write_text(json.dumps({
                "sha": SHA, "run_id": "123", "status": "passed",
                "source": "self-hosted-runner", "checks": list(REQUIRED)
            }))
            assert_receipt(SHA, receipt, run_id="123", runner_temp=temp)
            with self.assertRaises(RuntimeError):
                assert_receipt("b" * 40, receipt, run_id="123", runner_temp=temp)
            with self.assertRaises(RuntimeError):
                assert_receipt(SHA, receipt, run_id="321", runner_temp=temp)
            with self.assertRaises(RuntimeError):
                assert_receipt(SHA, receipt, run_id="local", runner_temp=temp)
            receipt.write_text(json.dumps({
                "sha": SHA, "run_id": "123", "status": "passed",
                "source": "self-hosted-runner", "checks": ["policy"]
            }))
            with self.assertRaises(RuntimeError):
                assert_receipt(SHA, receipt, run_id="123", runner_temp=temp)

    def test_cannot_use_receipt_outside_runner_temp(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            path = Path(two) / ("arvor-quality-" + SHA + ".json")
            path.write_text(json.dumps({
                "sha": SHA, "run_id": "123", "status": "passed",
                "source": "self-hosted-runner", "checks": list(REQUIRED)
            }))
            with self.assertRaises(RuntimeError):
                assert_receipt(SHA, path, run_id="123", runner_temp=Path(one))

    def test_test_database_fails_closed(self):
        base = {
            "PO_TEST_DATABASE_URL": "postgresql://po_test:ephemeral_ci_only@127.0.0.1:54323/po_test",
            "TRACE_TEST_DATABASE_URL": "postgresql://po_test:ephemeral_ci_only@127.0.0.1:54323/po_test",
            "PO_ALLOW_TEST_MIGRATION": "yes",
            "PO_DATABASE_URL": "postgresql://business:other@127.0.0.1:5432/arvor",
        }
        with patch.dict(os.environ, base):
            validate_test_database()
        with patch.dict(os.environ, dict(base, PO_TEST_DATABASE_URL=base["PO_DATABASE_URL"])):
            with self.assertRaises(RuntimeError):
                validate_test_database()


if __name__ == "__main__":
    unittest.main()
