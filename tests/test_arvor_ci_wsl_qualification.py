"""Guardrails for the one-command WSL qualification helper (no Docker required)."""
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "qualify_arvor_ci_wsl.sh"


class WslQualificationScriptTests(unittest.TestCase):
    @staticmethod
    def _git(root, *args):
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, check=True, timeout=5,
        )
        return proc.stdout.strip()

    def _fake_lab(self, temp, pr=214):
        lab = Path(temp) / "arvor-lab"
        controller = lab / "ci-source"
        candidate = lab / f"pr{pr}"
        ci_bin = lab / "ci-venv" / "bin"
        fakebin = Path(temp) / "fakebin"
        for path in (controller, candidate, ci_bin, fakebin):
            path.mkdir(parents=True)
        for name in (
            "arvor_local_ci.py", "arvor_ci_gate.py",
            "arvor_ci_trusted_unittest.py", "arvor_ci_supervised_entrypoint.sh",
            "arvor_ci_trusted_gitleaks.toml", "arvor_ci_trusted_gitleaksignore",
        ):
            path = controller / "scripts" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("trusted fixture", encoding="utf-8")
        (controller / "ci" / "local").mkdir(parents=True)
        (controller / "ci" / "local" / "Dockerfile").write_text(
            "FROM scratch\n", encoding="utf-8")
        (candidate / "README.md").write_text("candidate", encoding="utf-8")
        for root in (controller, candidate):
            subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=5)
            self._git(root, "config", "user.email", "ci-test@example.invalid")
            self._git(root, "config", "user.name", "CI Test")
            self._git(root, "add", ".")
            self._git(root, "commit", "-qm", "fixture")

        docker = fakebin / "docker"
        docker.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  info) exit 0;;\n"
            "  build) [ \"${MOCK_BUILD_FAIL:-0}\" != 1 ];;\n"
            "  image) printf 'sha256:'; printf '%064d\\n' 0;;\n"
            "  *) exit 88;;\n"
            "esac\n", encoding="utf-8")
        docker.chmod(0o755)
        python = ci_bin / "python"
        python.write_text(
            "#!/bin/bash\n"
            "set -eu\n"
            "if [ \"${1:-}\" = -c ]; then printf '%064d\\n' 0; exit 0; fi\n"
            "[ \"$1\" = -m ] || exit 88\n"
            "case \"$2\" in\n"
            "  unittest) exit 0;;\n"
            "  scripts.arvor_ci_host_supervisor)\n"
            "    shift 2\n"
            "    while [ \"$#\" -gt 0 ]; do\n"
            "      if [ \"$1\" = --evidence ]; then\n"
            "        printf '{}\\n' > \"$2/mock-receipt.json\"\n"
            "        exit 0\n"
            "      fi\n"
            "      shift\n"
            "    done\n"
            "    exit 89;;\n"
            "  scripts.arvor_ci_evidence_verify) exit 0;;\n"
            "  *) exit 90;;\n"
            "esac\n", encoding="utf-8")
        python.chmod(0o755)
        return (
            lab, controller, candidate,
            {**os.environ, "ARVOR_CI_LAB_DIR": str(lab),
             "PATH": str(fakebin) + os.pathsep + os.environ["PATH"]},
        )

    def test_bash_syntax(self):
        proc = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_invalid_sha_blocks_before_side_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            proc = subprocess.run(
                ["bash", str(SCRIPT), "bad-sha", "214", "b" * 40, "c" * 40],
                env={**os.environ, "ARVOR_CI_LAB_DIR": temp},
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("controller SHA incomplet", proc.stderr)
            self.assertEqual(list(Path(temp).iterdir()), [])

    def test_missing_lab_blocks_before_docker(self):
        with tempfile.TemporaryDirectory() as temp:
            absent = Path(temp) / "absent"
            proc = subprocess.run(
                ["bash", str(SCRIPT), "a" * 40, "214", "b" * 40, "c" * 40],
                env={**os.environ, "ARVOR_CI_LAB_DIR": str(absent)},
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("lab absent", proc.stderr)
            self.assertFalse(absent.exists())

    def test_script_has_no_delivery_or_merge_command(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in (
            "git reset --hard", "git switch", "git push", "gh pr merge",
            "scripts/deploy_local.py", "docker compose down",
            "LOCAL_PC_ENABLED=", "LOCAL_PC_APPROVED_SHA=",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn("arvor_ci_evidence_verify", source)
        self.assertIn("SECURITY_AUDIT_REFRESH", source)
        self.assertIn("Provenance host independante verifiee; signature et publication distinctes.", source)

    def test_orchestration_with_stubbed_services_uses_fresh_private_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            lab, controller, candidate, env = self._fake_lab(temp, pr=318)
            head = self._git(controller, "rev-parse", "HEAD")
            pr_head = self._git(candidate, "rev-parse", "HEAD")
            proc = subprocess.run(
                ["bash", str(SCRIPT), head, "318", pr_head, pr_head],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("LOCAL_GATES_AND_LOG_INTEGRITY_PASS", proc.stdout)
            trusted = list(lab.glob("trusted-qualification.*"))
            evidence = list(lab.glob("evidence-qualification.*"))
            self.assertEqual((len(trusted), len(evidence)), (1, 1))
            self.assertEqual(stat.S_IMODE(trusted[0].stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(evidence[0].stat().st_mode), 0o700)
            self.assertEqual(len(list(trusted[0].iterdir())), 6)
            self.assertEqual(len(list(evidence[0].glob("*.json"))), 1)
            self.assertIn("Provenance host independante verifiee", proc.stdout)

    def test_dirty_candidate_blocks_before_image_build(self):
        with tempfile.TemporaryDirectory() as temp:
            lab, controller, candidate, env = self._fake_lab(temp)
            head = self._git(controller, "rev-parse", "HEAD")
            pr_head = self._git(candidate, "rev-parse", "HEAD")
            (candidate / "README.md").write_text("dirty", encoding="utf-8")
            proc = subprocess.run(
                ["bash", str(SCRIPT), head, "214", pr_head, pr_head],
                env=env, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("checkout modifie", proc.stderr)
            self.assertEqual(list(lab.glob("evidence-qualification.*")), [])

    def test_failed_audit_image_build_stops_without_false_green(self):
        with tempfile.TemporaryDirectory() as temp:
            lab, controller, candidate, env = self._fake_lab(temp)
            head = self._git(controller, "rev-parse", "HEAD")
            pr_head = self._git(candidate, "rev-parse", "HEAD")
            proc = subprocess.run(
                ["bash", str(SCRIPT), head, "214", pr_head, pr_head],
                env={**env, "MOCK_BUILD_FAIL": "1"},
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("build/audit image KO", proc.stderr)
            self.assertNotIn("LOCAL_GATES_AND_LOG_INTEGRITY_PASS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
