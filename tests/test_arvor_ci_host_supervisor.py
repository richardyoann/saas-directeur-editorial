"""Safety/negative-path tests for host-supervised Arvor CI (no Docker needed)."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import arvor_ci_host_supervisor as s

SHA = "a" * 40
BASE = "b" * 40
IMAGE = "sha256:" + "c" * 64
CID = "d" * 64


def inspect_payload(*, mount_rw=False, network="none", image=IMAGE,
                    evidence_mount=False, security="no-new-privileges:true"):
    mounts = [
        {"Type": "bind", "Destination": "/workspace", "Source": "/candidate", "RW": mount_rw},
        {"Type": "bind", "Destination": "/trusted", "Source": "/trusted", "RW": False},
    ]
    if evidence_mount:
        mounts.append({"Type": "bind", "Destination": "/evidence",
                       "Source": "/host-evidence", "RW": True})
    return [{"Image": image, "HostConfig": {
        "NetworkMode": network, "ReadonlyRootfs": True,
        "CapDrop": ["ALL"], "SecurityOpt": [security],
    }, "Config": {"User": "999:999"}, "Mounts": mounts}]


class HostSupervisorTests(unittest.TestCase):
    def test_isolated_docker_command_has_no_writable_evidence(self):
        cmd = s.docker_command(IMAGE, Path("/candidate"), Path("/trusted"),
                               SHA, BASE, 214, "arvor-host-ci-test")
        for option in ("--network=none", "--read-only", "--cap-drop=ALL",
                       "--security-opt=no-new-privileges", "--user=999:999",
                       "--pull=never"):
            self.assertIn(option, cmd)
        self.assertFalse(any("/evidence" in x for x in cmd))
        self.assertFalse(any("docker.sock" in x for x in cmd))
        self.assertEqual(sum("target=/workspace" in x for x in cmd), 1)
        self.assertEqual(sum("target=/trusted" in x for x in cmd), 1)
        self.assertTrue(any("target=/workspace,readonly" in x for x in cmd))
        self.assertTrue(any("target=/trusted,readonly" in x for x in cmd))

    def test_read_only_inspection_accepts_trusted_setup(self):
        with patch.object(s, "call", return_value=json.dumps(inspect_payload())):
            self.assertTrue(s.inspect_isolation(CID, Path("/candidate"),
                                                 Path("/trusted"), IMAGE))

    def test_docker_inspection_rejects_runtime_security_violations(self):
        cases = (
            {"mount_rw": True}, {"network": "bridge"},
            {"image": "sha256:" + "e" * 64},
            {"evidence_mount": True}, {"security": "label=disabled"},
            {"security": "no-new-privileges:false"},
        )
        for modification in cases:
            with self.subTest(modification=modification):
                with patch.object(s, "call", return_value=json.dumps(inspect_payload(**modification))):
                    with self.assertRaisesRegex(ValueError, "Docker|mount|readonly|Evidence"):
                        s.inspect_isolation(CID, Path("/candidate"),
                                            Path("/trusted"), IMAGE)

    def test_docker_inspection_rejects_privileged_container(self):
        inspected = inspect_payload()
        inspected[0]["HostConfig"]["Privileged"] = True
        with patch.object(s, "call", return_value=json.dumps(inspected)):
            with self.assertRaisesRegex(ValueError, "Docker isolation"):
                s.inspect_isolation(CID, Path("/candidate"), Path("/trusted"), IMAGE)

    def test_gate_returns_fail_closed_even_if_stdout_looks_good(self):
        rc = SimpleNamespace(returncode=1)
        self.assertFalse(s._check_gate("regression_312", rc,
                          '{"tests":390,"failures":0,"errors":0,"skipped":0}')[0])
        self.assertFalse(s._check_gate("dependencies", rc, "ARVOR_AUDIT_STATUS=OK")[0])
        self.assertFalse(s._check_gate("video_75", rc,
                          '{"verified":true,"synthetic":true,"data_mutation":false,'
                          '"video_duration_seconds":75,"resolution":"720x1280","ffprobe":"passed"}')[0])

    def _run_mock(self, *, failed_gate=None):
        def run(argv, **kwargs):
            if argv[:2] == ["docker", "run"]:
                return SimpleNamespace(returncode=0, stdout=CID + "\n", stderr="")
            if argv[:3] == ["docker", "exec", CID] and "pg_isready" in argv:
                return SimpleNamespace(returncode=0, stdout="ready", stderr="")
            if argv[:2] == ["docker", "stop"]:
                return SimpleNamespace(returncode=0, stdout="stopped", stderr="")
            if "--gate" in argv:
                gate = argv[argv.index("--gate") + 1]
                if gate == failed_gate:
                    return SimpleNamespace(returncode=1, stdout="FAILED\n", stderr="")
                if gate.startswith("regression_"):
                    message = '{"tests":390,"failures":0,"errors":0,"skipped":0}\n'
                elif gate == "browser":
                    message = "Ran 18 tests in 0.4s\n\nOK\n"
                elif gate == "dependencies":
                    message = "ARVOR_AUDIT_STATUS=OK\n"
                elif gate == "video_75":
                    message = ('{"verified":true,"synthetic":true,"data_mutation":false,'
                               '"video_duration_seconds":75,"resolution":"720x1280","ffprobe":"passed"}\n')
                else:
                    message = "OK\n"
                return SimpleNamespace(returncode=0, stdout=message, stderr="")
            raise AssertionError("Unexpected host command: " + repr(argv))
        return run

    def _execute(self, failed_gate=None):
        with TemporaryDirectory() as folder:
            tmp = Path(folder)
            root, controller, trusted, evidence = (
                tmp / n for n in ("candidate", "controller", "trusted", "host-evidence")
            )
            for path in (root, controller, trusted, evidence):
                path.mkdir()
            for file in s.POLICY_FILES:
                (trusted / file).write_text("trusted-" + file)
            def git(_root, *args):
                return SHA if args == ("rev-parse", "HEAD") else ""
            with (patch.object(s, "validate_inputs",
                               return_value=(root, controller, trusted, evidence)),
                  patch.object(s, "git", side_effect=git),
                  patch.object(s, "inspect_isolation", return_value=True)):
                report = s.execute(IMAGE, root, trusted, evidence, SHA, BASE, 214, SHA,
                                   run=self._run_mock(failed_gate=failed_gate))
            receipts = list(evidence.glob("*.json"))
            self.assertEqual(len(receipts), 1)
            self.assertEqual(json.loads(receipts[0].read_text()), report)
            self.assertFalse(report["host_supervision"]["independent_execution_provenance_certified"])
            self.assertTrue(report["host_supervision"]["evidence_not_mounted"])
            self.assertEqual(len(list(evidence.glob("*.log"))), len(report["gates"]))
            return report

    def test_all_sixteen_host_owned_gate_exits_can_succeed(self):
        report = self._execute()
        self.assertEqual(report["status"], "success")
        self.assertEqual(len(report["gates"]), 16)
        self.assertTrue(all(x["returncode"] == 0 for x in report["gates"]))

    def test_failed_docker_exec_is_captured_and_blocks_overall_success(self):
        report = self._execute(failed_gate="dependencies")
        self.assertEqual(report["status"], "failure")
        self.assertEqual(len(report["gates"]), 12)
        self.assertEqual(report["gates"][-1]["name"], "dependencies")
        self.assertFalse(report["gates"][-1]["passed"])
        self.assertEqual(report["gates"][-1]["returncode"], 1)

    def test_supervised_entrypoint_requires_exact_candidate_pins(self):
        script = (Path(__file__).resolve().parents[1]
                  / "scripts/arvor_ci_supervised_entrypoint.sh").read_text()
        self.assertIn('Path("/workspace/requirements.txt")', script)
        self.assertIn("RECONSTRUCTION_IMAGE_REQUISE", script)
        self.assertNotIn("/evidence", script)


if __name__ == "__main__":
    unittest.main()
