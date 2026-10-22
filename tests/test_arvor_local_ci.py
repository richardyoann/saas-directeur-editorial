"""Negative-path tests for the local CI evidence and publisher. No network calls."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts import arvor_ci_attestation as attest
from scripts import arvor_local_ci as ci
from scripts import arvor_ci_publish as pub

SHA = "a" * 40
BASE = "b" * 40


def receipt(status="success"):
    import uuid
    now = datetime.now(timezone.utc)
    gates = []
    for name in ci.GATES:
        counts = {"tests": 3, "failures": 0, "errors": 0, "skipped": 0} if name.startswith("regression_") or name == "browser" else None
        gates.append({"name": name, "passed": True, "returncode": 0, "log_sha256": "c" * 64, "tests": counts})
    if status == "failure":
        gates[-1]["passed"] = False
        gates[-1]["returncode"] = 1
    return {"schema": "arvor-local-ci-v1", "run_id": str(uuid.uuid4()),
            "repo": pub.REPO, "pr": 215, "sha": SHA, "base_sha": BASE,
            "started_at": (now - timedelta(seconds=7)).isoformat(),
            "finished_at": now.isoformat(), "source": "isolated-local-tests",
            "status": status, "gates": gates}


class LocalCITests(unittest.TestCase):
    def setUp(self):
        key = Ed25519PrivateKey.generate()
        self.private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        self.public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def signed(self, report=None):
        return attest.sign(report or receipt(), self.private, "k1")

    def test_valid_signed_success(self):
        r = receipt()
        e = self.signed(r)
        self.assertEqual(attest.verify(e, self.public, "k1"), r)
        self.assertEqual(pub.prepare(e, self.public, "k1")[1], "success")

    def test_payload_tampering(self):
        e = self.signed()
        e["evidence"]["sha"] = "d" * 40
        with self.assertRaises(ValueError):
            attest.verify(e, self.public, "k1")

    def test_unknown_signing_key(self):
        e = self.signed()
        other = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        with self.assertRaises(ValueError):
            attest.verify(e, other, "k1")

    def test_skipped_tests_rejected(self):
        r = receipt()
        r["gates"][1]["tests"]["skipped"] = 1
        with self.assertRaises(ValueError):
            self.signed(r)

    def test_missing_gate_rejected(self):
        r = receipt()
        r["gates"].pop()
        with self.assertRaises(ValueError):
            self.signed(r)

    def test_fake_success_rejected(self):
        r = receipt()
        r["gates"][0]["returncode"] = 1
        with self.assertRaises(ValueError):
            self.signed(r)

    def test_signed_failure(self):
        e = self.signed(receipt("failure"))
        self.assertEqual(pub.prepare(e, self.public, "k1")[1], "failure")

    def test_expired_receipt_rejected(self):
        r = receipt()
        r["started_at"] = (datetime.now(timezone.utc) - timedelta(hours=4, seconds=7)).isoformat()
        r["finished_at"] = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        with self.assertRaises(ValueError):
            pub.prepare(self.signed(r), self.public, "k1")

    def test_stale_pull_request_head(self):
        def fake(method, url, token):
            return {"state": "open", "merged": False,
                    "head": {"sha": "f" * 40, "repo": {"full_name": pub.REPO}},
                    "base": {"sha": BASE, "ref": "main"}}
        with self.assertRaises(ValueError):
            pub.verify_remote(receipt(), "mock", fake)

    def test_changed_base_commit(self):
        def fake(method, url, token):
            return {"state": "open", "merged": False,
                    "head": {"sha": SHA, "repo": {"full_name": pub.REPO}},
                    "base": {"sha": "f" * 40, "ref": "main"}}
        with self.assertRaises(ValueError):
            pub.verify_remote(receipt(), "mock", fake)

    def test_db_isolation_rules(self):
        u = "postgresql://po_test:ephemeral_ci_only@127.0.0.1:55483/po_test"
        good = {"PO_TEST_DATABASE_URL": u, "TRACE_TEST_DATABASE_URL": u, "PO_ALLOW_TEST_MIGRATION": "yes"}
        ci.validate_db(good)
        with self.assertRaises(ValueError):
            ci.validate_db({**good, "PO_DATABASE_URL": u})
        with self.assertRaises(ValueError):
            ci.validate_db({**good, "PO_ALLOW_TEST_MIGRATION": "no"})

    def test_report_parsing(self):
        self.assertIsNone(ci.regression_counts("OK without json"))
        self.assertIsNone(ci.browser_counts("Ran 1 test in 0.01s\nOK (skipped=1)"))
        self.assertEqual(ci.regression_counts('{"tests":12,"failures":0,"errors":0,"skipped":0}')["tests"], 12)

    def test_publish_once_without_live_network(self):
        calls = []
        def fake(method, url, token=None, payload=None):
            calls.append(method)
            if method == "GET":
                return {"state": "open", "merged": False, "head": {"sha": SHA, "repo": {"full_name": pub.REPO}},
                        "base": {"sha": BASE, "ref": "main"}}
            if "/statuses/" in url:
                return {"state": "success"}
            return {"ok": True}
        envelope = self.signed()
        with TemporaryDirectory() as folder:
            self.assertEqual(pub.publish(envelope, self.public, "k1", "mock", "https://hooks.slack.com/services/mock",
                                         Path(folder), request=fake), "success")
            with self.assertRaises(ValueError):
                pub.publish(envelope, self.public, "k1", "mock", None, Path(folder), request=fake)
        self.assertEqual(calls, ["GET", "POST", "POST"])


if __name__ == "__main__":
    unittest.main()
