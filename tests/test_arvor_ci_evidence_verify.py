"""Host provenance verification tests; Docker is represented by captured inspect evidence."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import arvor_ci_evidence_verify as verifier
from scripts.arvor_ci_trust import (
    POLICY_VERSION, SANDBOX_POLICY_FILES, canonical_json, policy_digest, policy_snapshot,
)
from scripts.arvor_local_ci import GATES

SHA = "a" * 40
BASE = "b" * 40
CONTROLLER_SHA = "c" * 40
IMAGE = "sha256:" + "d" * 64


def sha(data):
    return hashlib.sha256(data).hexdigest()


class EvidenceVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.evidence = self.root / "evidence"
        self.checkout = self.root / "candidate"
        self.trusted = self.root / "trusted-policy"
        self.evidence.mkdir(mode=0o700)
        self.checkout.mkdir()
        self.trusted.mkdir(mode=0o755)
        self.controller = Path(verifier.__file__).resolve().parents[1]
        for filename in SANDBOX_POLICY_FILES:
            (self.trusted / filename).write_bytes((self.controller / "scripts" / filename).read_bytes())
            (self.trusted / filename).chmod(0o644)

        self.now = datetime.now(timezone.utc)
        self.run_id = str(uuid4())
        self.gates = []
        self.execs = []
        for name in GATES:
            counts = None
            if name.startswith("regression_"):
                counts = {"tests": 390, "failures": 0, "errors": 0, "skipped": 0}
                log = "Ran 390 tests in 1s\n\nOK\n" + json.dumps(counts) + "\n"
            elif name == "browser":
                counts = {"tests": 18, "failures": 0, "errors": 0, "skipped": 0}
                log = "Ran 18 tests in 1s\n\nOK\n"
            elif name == "dependencies":
                log = "ARVOR_AUDIT_STATUS=OK\n"
            elif name == "video_75":
                log = json.dumps({"verified": True, "synthetic": True,
                    "video_duration_seconds": 75, "resolution": "720x1280",
                    "ffprobe": "passed", "data_mutation": False}) + "\n"
            else:
                log = "OK\n"
            raw = log.encode()
            (self.evidence / f"{self.run_id}-{name}.log").write_bytes(raw)
            (self.evidence / f"{self.run_id}-{name}.log").chmod(0o600)
            digest = sha(raw)
            self.gates.append({"name": name, "passed": True, "returncode": 0,
                               "tests": counts, "log_sha256": digest})
            argv = ["docker", "exec", "--user=999:999", "--workdir=/workspace",
                "f" * 64, "/opt/arvor/py314/bin/python", "/trusted/arvor_ci_gate.py",
                "--gate", name, "--base-sha", BASE]
            self.execs.append({"name": name, "docker_exec_returncode": 0,
                "log_sha256": digest, "gate_command_sha256": sha(canonical_json(argv))})

        self.inspect = {
            "Id": "f" * 64, "Image": IMAGE,
            "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True,
                "Privileged": False, "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"]},
            "Config": {"User": "999:999"},
            "Mounts": [
                {"Type": "bind", "Destination": "/workspace", "Source": str(self.checkout), "RW": False},
                {"Type": "bind", "Destination": "/trusted", "Source": str(self.trusted), "RW": False},
                {"Type": "tmpfs", "Destination": "/tmp", "RW": True},
                {"Type": "tmpfs", "Destination": "/var/lib/postgresql/data", "RW": True},
                {"Type": "tmpfs", "Destination": "/run/postgresql", "RW": True},
            ],
        }
        self.observation = {
            "schema": "arvor-host-observation-v1", "run_id": self.run_id,
            "repo": "richardyoann/saas-directeur-editorial", "pr": 214,
            "sha": SHA, "base_sha": BASE, "controller_sha": CONTROLLER_SHA,
            "policy_version": POLICY_VERSION, "policy_files_sha256": policy_snapshot(self.controller),
            "policy_sha256": policy_digest(self.controller), "image_id": IMAGE,
            "container_id": "f" * 64, "docker_inspect": self.inspect,
            "gate_exec_observations": self.execs,
            "started_at": (self.now - timedelta(minutes=1)).isoformat(),
            "finished_at": self.now.isoformat(), "docker_stop_returncode": 0,
        }
        self.host_file = self.evidence / f"{self.run_id}.host.json"
        self.receipt_file = self.evidence / f"{self.run_id}.json"
        self.report = {
            "schema": "arvor-local-ci-v1", "run_id": self.run_id,
            "repo": "richardyoann/saas-directeur-editorial", "pr": 214,
            "sha": SHA, "base_sha": BASE,
            "started_at": (self.now - timedelta(minutes=1)).isoformat(),
            "finished_at": self.now.isoformat(), "source": "isolated-local-tests",
            "status": "success", "gates": self.gates,
        }
        self.save()

    def save(self):
        host_bytes = canonical_json(self.observation) + b"\n"
        self.host_file.write_bytes(host_bytes)
        self.host_file.chmod(0o600)
        self.report["host_supervision"] = {
            "version": 2, "controller_sha": CONTROLLER_SHA,
            "policy_version": POLICY_VERSION,
            "policy_files_sha256": self.observation["policy_files_sha256"],
            "policy_sha256": self.observation["policy_sha256"],
            "image_id": IMAGE, "container_id": "f" * 64,
            "host_observation_sha256": sha(host_bytes),
        }
        self.receipt_file.write_text(json.dumps(self.report), encoding="utf-8")
        self.receipt_file.chmod(0o600)

    def run_verification(self, **overrides):
        args = {
            "host_observation_file": self.host_file,
            "trusted_controller": self.controller,
            "trusted_policy": self.trusted,
            "controller_sha": CONTROLLER_SHA,
            "expected_image_id": IMAGE,
            "expected_policy_sha256": policy_digest(self.controller),
            "now": self.now + timedelta(seconds=1),
        }
        args.update(overrides)
        with patch("scripts.arvor_ci_evidence_verify.git",
                   side_effect=[CONTROLLER_SHA, "", SHA, "", BASE]), \
             patch("scripts.arvor_ci_evidence_verify.subprocess.run",
                   return_value=SimpleNamespace(returncode=0)):
            return verifier.verify_receipt(
                self.receipt_file, self.evidence, self.checkout, SHA, BASE, 214,
                **args,
            )

    def test_valid_host_observation_and_sixteen_logs_certify_provenance(self):
        summary, validated, provenance = self.run_verification(include_validated_receipt=True)
        self.assertEqual(summary["verified_logs"], 16)
        self.assertTrue(summary["independent_execution_provenance_verified"])
        self.assertEqual(provenance["controller_sha"], CONTROLLER_SHA)
        self.assertEqual(validated, self.report)

    def test_tampered_receipt_or_host_journal_rejected(self):
        self.report["sha"] = "9" * 40
        self.save()
        with self.assertRaises(ValueError):
            self.run_verification()
        self.report["sha"] = SHA
        self.save()
        self.observation["docker_inspect"]["HostConfig"]["NetworkMode"] = "bridge"
        self.save()
        with self.assertRaisesRegex(ValueError, "digest|isolation"):
            self.run_verification()

    def test_changed_log_rejected_even_if_receipt_digest_is_rewritten(self):
        log = self.evidence / f"{self.run_id}-browser.log"
        log.write_text("FORGED\n")
        log.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "Log digest"):
            self.run_verification()

    def test_wrong_sha_base_controller_image_or_policy_rejected(self):
        cases = (
            {"controller_sha": "9" * 40},
            {"expected_image_id": "sha256:" + "9" * 64},
            {"expected_policy_sha256": "9" * 64},
        )
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_verification(**kwargs)
        with self.assertRaises(ValueError):
            with patch("scripts.arvor_ci_evidence_verify.git",
                       side_effect=["9" * 40]):
                verifier.verify_receipt(self.receipt_file, self.evidence,
                    self.checkout, "9" * 40, BASE, 214,
                    host_observation_file=self.host_file,
                    trusted_controller=self.controller, trusted_policy=self.trusted,
                    controller_sha=CONTROLLER_SHA,
                    expected_image_id=IMAGE, expected_policy_sha256=policy_digest(self.controller),
                    now=self.now)
        with self.assertRaises(ValueError):
            with patch("scripts.arvor_ci_evidence_verify.git", side_effect=[SHA, "", "9" * 40]):
                verifier.verify_receipt(self.receipt_file, self.evidence,
                    self.checkout, SHA, "9" * 40, 214,
                    host_observation_file=self.host_file,
                    trusted_controller=self.controller, trusted_policy=self.trusted,
                    controller_sha=CONTROLLER_SHA,
                    expected_image_id=IMAGE, expected_policy_sha256=policy_digest(self.controller),
                    now=self.now)

    def test_future_and_expired_receipts_and_host_observations_rejected(self):
        cases = (
            (self.now - timedelta(minutes=1), self.now + timedelta(hours=1)),
            (self.now - timedelta(hours=4), self.now - timedelta(hours=3)),
        )
        for started, finished in cases:
            with self.subTest(finished=finished):
                self.observation["started_at"] = started.isoformat()
                self.observation["finished_at"] = finished.isoformat()
                self.report["started_at"] = started.isoformat()
                self.report["finished_at"] = finished.isoformat()
                self.save()
                with self.assertRaisesRegex(ValueError, "future-dated|expired"):
                    self.run_verification()
        self.observation["started_at"] = (self.now - timedelta(minutes=1)).isoformat()
        self.observation["finished_at"] = self.now.isoformat()
        self.report["started_at"] = (self.now - timedelta(minutes=1)).isoformat()
        self.report["finished_at"] = self.now.isoformat()
        self.save()
        self.report["finished_at"] = (self.now + timedelta(hours=1)).isoformat()
        self.save()
        with self.assertRaisesRegex(ValueError, "future-dated|expired"):
            self.run_verification()

    def test_missing_failed_timeout_skip_or_reordered_gate_rejected(self):
        for change in ("missing", "failed", "timeout", "skip", "reordered"):
            with self.subTest(change=change):
                self.report["gates"] = [dict(x) for x in self.gates]
                self.observation["gate_exec_observations"] = [dict(x) for x in self.execs]
                if change == "missing":
                    self.report["gates"].pop()
                elif change == "failed":
                    self.report["gates"][0]["passed"] = False
                elif change == "timeout":
                    self.observation["gate_exec_observations"][0]["docker_exec_returncode"] = 124
                elif change == "skip":
                    self.report["gates"][1]["tests"]["skipped"] = 1
                else:
                    self.report["gates"][0], self.report["gates"][1] = self.report["gates"][1], self.report["gates"][0]
                self.save()
                with self.assertRaises(ValueError):
                    self.run_verification()

    def test_host_observation_is_mandatory_not_receipt_booleans(self):
        self.report["host_supervision"]["independent_execution_provenance_certified"] = True
        self.save()
        self.host_file.unlink()
        with self.assertRaises((OSError, ValueError)):
            self.run_verification()

    def test_published_policy_copy_must_match_pinned_controller(self):
        (self.trusted / SANDBOX_POLICY_FILES[0]).write_text("# attacker policy\n")
        (self.trusted / SANDBOX_POLICY_FILES[0]).chmod(0o644)
        with self.assertRaisesRegex(ValueError, "policy copy"):
            self.run_verification()

    def test_symlink_journal_is_rejected(self):
        other = self.root / "saved-host"
        self.host_file.rename(other)
        self.host_file.symlink_to(other)
        with self.assertRaises(OSError):
            self.run_verification()


if __name__ == "__main__":
    unittest.main()
