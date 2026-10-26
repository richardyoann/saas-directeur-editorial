"""Negative-path tests for the local CI evidence and publisher. No network calls."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from tempfile import TemporaryDirectory
import unittest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts import arvor_ci_attestation as attest
from scripts import arvor_local_ci as ci
from scripts import arvor_ci_publish as pub

SHA = "a" * 40
BASE = "b" * 40
CONTROLLER_SHA = "c" * 40
POLICY_SHA = "d" * 64
IMAGE_ID = "sha256:" + "e" * 64
HOST_SHA = "f" * 64


def provenance(r):
    return {"schema": "arvor-verified-provenance-v1",
        "controller_sha": CONTROLLER_SHA,
        "policy_version": "arvor-local-ci-policy-v2",
        "policy_sha256": POLICY_SHA,
        "policy_files_sha256": {"scripts/arvor_ci_trust.py": "1" * 64},
        "image_id": IMAGE_ID, "host_observation_sha256": HOST_SHA,
        "run_id": r["run_id"], "verified_at": datetime.now(timezone.utc).isoformat()}


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
    report = {"schema": "arvor-local-ci-v1", "run_id": str(uuid.uuid4()),
            "repo": pub.REPO, "pr": 215, "sha": SHA, "base_sha": BASE,
            "started_at": (now - timedelta(seconds=7)).isoformat(),
            "finished_at": now.isoformat(), "source": "isolated-local-tests",
            "status": status, "gates": gates}
    report["host_supervision"] = {"controller_sha": CONTROLLER_SHA,
        "policy_version": "arvor-local-ci-policy-v2", "policy_sha256": POLICY_SHA,
        "policy_files_sha256": provenance(report)["policy_files_sha256"],
        "image_id": IMAGE_ID, "host_observation_sha256": HOST_SHA}
    return report


class LocalCITests(unittest.TestCase):
    def setUp(self):
        key = Ed25519PrivateKey.generate()
        self.private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        self.public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def signed(self, report=None):
        report = report or receipt()
        return attest.sign(report, self.private, "k1", provenance(report))

    def test_valid_signed_success(self):
        r = receipt()
        e = self.signed(r)
        self.assertEqual(attest.verify(e, self.public, "k1"), r)
        self.assertEqual(pub.prepare(e, self.public, "k1", controller_sha=CONTROLLER_SHA,
            expected_policy_sha256=POLICY_SHA, expected_image_id=IMAGE_ID)[1], "success")

    def test_payload_tampering(self):
        e = self.signed()
        e["evidence"]["sha"] = "d" * 40
        with self.assertRaises(ValueError):
            attest.verify(e, self.public, "k1")

    def test_altered_signature_is_rejected(self):
        envelope = self.signed()
        envelope["signature"] = envelope["signature"][:-4] + "AAAA"
        with self.assertRaises(ValueError):
            attest.verify(envelope, self.public, "k1")

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
        self.assertEqual(pub.prepare(e, self.public, "k1", controller_sha=CONTROLLER_SHA,
            expected_policy_sha256=POLICY_SHA, expected_image_id=IMAGE_ID)[1], "failure")

    def test_expired_receipt_rejected(self):
        r = receipt()
        r["started_at"] = (datetime.now(timezone.utc) - timedelta(hours=4, seconds=7)).isoformat()
        r["finished_at"] = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        with self.assertRaises(ValueError):
            pub.prepare(self.signed(r), self.public, "k1",
                controller_sha=CONTROLLER_SHA, expected_policy_sha256=POLICY_SHA,
                expected_image_id=IMAGE_ID)

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
            if method == "GET" and url.endswith("/statuses/" + SHA):
                return []
            if method == "GET":
                return {"state": "open", "merged": False, "head": {"sha": SHA, "repo": {"full_name": pub.REPO}},
                        "base": {"sha": BASE, "ref": "main"}}
            if "/statuses/" in url:
                return {"state": "success"}
            return {"ok": True}
        envelope = self.signed()
        with TemporaryDirectory() as folder:
            self.assertEqual(pub.publish(envelope, self.public, "k1", "mock", "https://hooks.slack.com/services/mock",
                                         Path(folder), controller_sha=CONTROLLER_SHA,
                                         expected_policy_sha256=POLICY_SHA,
                                         expected_image_id=IMAGE_ID,
                                         request=fake), "success")
            with self.assertRaises(ValueError):
                pub.publish(envelope, self.public, "k1", "mock", None, Path(folder),
                    controller_sha=CONTROLLER_SHA, expected_policy_sha256=POLICY_SHA,
                    expected_image_id=IMAGE_ID, request=fake)
        self.assertEqual(calls, ["GET", "GET", "GET", "POST", "GET", "POST"])


    def test_remote_head_change_between_preflight_and_status_post_blocks_publish(self):
        pr_reads = 0
        writes = []
        def fake(method, url, token=None, payload=None):
            nonlocal pr_reads
            if method == "GET" and url.endswith("/statuses/" + SHA):
                return []
            if method == "GET":
                pr_reads += 1
                head = SHA if pr_reads == 1 else "9" * 40
                return {"state": "open", "merged": False,
                        "head": {"sha": head, "repo": {"full_name": pub.REPO}},
                        "base": {"sha": BASE, "ref": "main"}}
            writes.append(url)
            return {"state": "success"}
        with TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "revision"):
                pub.publish(self.signed(), self.public, "k1", "mock",
                    "https://hooks.slack.com/services/mock", Path(folder),
                    controller_sha=CONTROLLER_SHA, expected_policy_sha256=POLICY_SHA,
                    expected_image_id=IMAGE_ID, request=fake)
        self.assertEqual(writes, [])

    def test_ambiguous_github_status_post_is_reconciled_without_duplicate(self):
        statuses = []
        writes = {"github": 0, "slack": 0}
        def fake(method, url, token=None, payload=None):
            if method == "GET" and url.endswith("/statuses/" + SHA):
                return list(statuses)
            if method == "GET":
                return {"state": "open", "merged": False,
                        "head": {"sha": SHA, "repo": {"full_name": pub.REPO}},
                        "base": {"sha": BASE, "ref": "main"}}
            if "/statuses/" in url:
                writes["github"] += 1
                statuses.append({"context": payload["context"],
                                 "target_url": payload["target_url"],
                                 "state": payload["state"]})
                if writes["github"] == 1:
                    raise ConnectionError("lost response after GitHub stored status")
                return {"state": payload["state"]}
            writes["slack"] += 1
            return {"ok": True}
        envelope = self.signed()
        with TemporaryDirectory() as folder:
            with self.assertRaises(ConnectionError):
                pub.publish(envelope, self.public, "k1", "mock",
                    "https://hooks.slack.com/services/mock", Path(folder),
                    controller_sha=CONTROLLER_SHA, expected_policy_sha256=POLICY_SHA,
                    expected_image_id=IMAGE_ID, request=fake)
            self.assertEqual(pub.publish(envelope, self.public, "k1", "mock",
                "https://hooks.slack.com/services/mock", Path(folder),
                controller_sha=CONTROLLER_SHA, expected_policy_sha256=POLICY_SHA,
                expected_image_id=IMAGE_ID, request=fake), "success")
        self.assertEqual(writes, {"github": 1, "slack": 1})

    def test_video_75_refuses_zero_exit_without_valid_receipt(self):
        """No video success without the exact 75s ffprobe JSON evidence."""
        from types import SimpleNamespace
        def fake_command(argv, **kwargs):
            command = " ".join(map(str, argv))
            if "run_regression.py" in command:
                output = '{"tests":390,"failures":0,"errors":0,"skipped":0}\n'
            elif "test_studio_browser.py" in command:
                output = "Ran 18 tests in 0.01s\n\nOK\n"
            elif "smoke_video_75" in command:
                output = '{"verified":false,"synthetic":true,"video_duration_seconds":75,"resolution":"720x1280","ffprobe":"passed"}\n'
            elif "audit_snapshot.py" in command:
                output = "ARVOR_AUDIT_STATUS=OK\n"
            else:
                output = "OK\n"
            return SimpleNamespace(stdout=output, stderr="", returncode=0)
        test_url = "postgresql://po_test:ephemeral_ci_only@127.0.0.1:5432/po_test"
        env = {"ARVOR_CI_ISOLATED": "1", "PO_TEST_DATABASE_URL": test_url,
               "TRACE_TEST_DATABASE_URL": test_url, "PO_ALLOW_TEST_MIGRATION": "yes"}
        with TemporaryDirectory() as folder, patch.object(ci, "git", side_effect=[SHA, "", BASE, SHA, ""]), \
                patch.object(ci.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            output, report = ci.execute(Path(folder), SHA, BASE, 215, pub.REPO,
                                        Path("/fake/python312"), Path("/fake/python314"),
                                        Path(folder) / "evidence", env=env, run_command=fake_command)
            self.assertEqual(report["status"], "failure")
            self.assertEqual(report["gates"][-1]["name"], "video_75")
            self.assertFalse(report["gates"][-1]["passed"])

    def test_audit_diagnostics_remain_fail_closed(self):
        self.assertEqual(ci.audit_diagnostic("ARVOR_AUDIT_STATUS=PREUVE_PERIMEE", 1), "PREUVE_PERIMEE")
        self.assertEqual(ci.audit_diagnostic("ARVOR_AUDIT_STATUS=VULNERABLE", 1), "VULNERABLE")
        self.assertEqual(ci.audit_diagnostic("ARVOR_AUDIT_STATUS=ERREUR_INFRA", 1), "ERREUR_INFRA")
        self.assertEqual(ci.audit_diagnostic("ARVOR_AUDIT_STATUS=OK", 0), "OK")
        self.assertEqual(ci.audit_diagnostic("ARVOR_AUDIT_STATUS=OK", 1), "ERREUR_INFRA")
        self.assertEqual(ci.audit_diagnostic("No audit proof", 0), "PREUVE_NON_CORRESPONDANTE")
        self.assertEqual(ci.audit_diagnostic("No audit proof", 1), "ERREUR_INFRA")
        self.assertEqual(ci.audit_diagnostic("ARVOR_AUDIT_STATUS=VULNERABLE", 0),
                         "PREUVE_NON_CORRESPONDANTE")

    def test_slack_failure_requires_confirmation_and_retry_does_not_duplicate_github(self):
        calls = {"github": 0, "slack": 0}
        def fake(method, url, token=None, payload=None):
            if method == "GET" and url.endswith("/statuses/" + SHA):
                return []
            if method == "GET":
                return {"state": "open", "merged": False,
                        "head": {"sha": SHA, "repo": {"full_name": pub.REPO}},
                        "base": {"sha": BASE, "ref": "main"}}
            if "/statuses/" in url:
                calls["github"] += 1
                return {"state": "success"}
            calls["slack"] += 1
            if calls["slack"] == 1:
                raise ConnectionError("simulated Slack outage")
            return {"ok": True}
        e = self.signed()
        with TemporaryDirectory() as folder:
            with self.assertRaises(ConnectionError):
                pub.publish(e, self.public, "k1", "mock", "https://hooks.slack.com/services/mock", Path(folder),
                    controller_sha=CONTROLLER_SHA, expected_policy_sha256=POLICY_SHA,
                    expected_image_id=IMAGE_ID, request=fake)
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                pub.publish(e, self.public, "k1", "mock", "https://hooks.slack.com/services/mock", Path(folder),
                    controller_sha=CONTROLLER_SHA, expected_policy_sha256=POLICY_SHA,
                    expected_image_id=IMAGE_ID, request=fake)
            self.assertEqual(pub.publish(e, self.public, "k1", "mock", "https://hooks.slack.com/services/mock",
                Path(folder), controller_sha=CONTROLLER_SHA, expected_policy_sha256=POLICY_SHA,
                expected_image_id=IMAGE_ID,
                confirm_slack_not_delivered=True, request=fake), "success")
        self.assertEqual(calls, {"github": 1, "slack": 2})


if __name__ == "__main__":
    unittest.main()
