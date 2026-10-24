"""Host-owned isolated CI supervisor. Never run from the untrusted PR checkout.

Each gate is launched by the trusted host through Docker exec. Docker, not a
PR-supplied receipt, supplies the observed return code. Only the host writes
logs and receipt: the sandbox has NO evidence mount, credentials or Docker
socket. This improves provenance but is not remote/cryptographic attestation.
No signing, GitHub statuses, merges or deployments.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4

from scripts.arvor_local_ci import (
    GATES, audit_diagnostic, browser_counts, regression_counts,
)
from scripts.arvor_ci_evidence_verify import video_proof

SHA = re.compile(r"[a-f0-9]{40}\Z")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
POLICY_FILES = (
    "arvor_local_ci.py", "arvor_ci_gate.py",
    "arvor_ci_supervised_entrypoint.sh",
)
REPO = "richardyoann/saas-directeur-editorial"


def now():
    return datetime.now(timezone.utc).isoformat()


def call(argv, *, cwd=None, timeout=30):
    return subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True,
        check=True, timeout=timeout,
    ).stdout.strip()


def git(root, *args):
    return call(["git", "-C", str(root), *args])


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_inputs(image, checkout, trusted, evidence, sha, base, pr):
    if not IMAGE.fullmatch(image) or not SHA.fullmatch(sha) or not SHA.fullmatch(base):
        raise ValueError("Immutable image ID and exact Git SHAs required")
    if type(pr) is not int or pr < 1:
        raise ValueError("Positive PR ID required")
    root = checkout.resolve(strict=True)
    controller = Path(__file__).resolve().parent.parent
    trusted = trusted.resolve(strict=True)
    dest = evidence.resolve(strict=True)
    if any(not x.is_dir() for x in (root, controller, trusted, dest)):
        raise ValueError("All roots must exist")
    if (len({root, controller, trusted, dest}) != 4 or
            any(a.is_relative_to(b) for a in (root, trusted, dest)
                for b in (root, trusted, dest) if a != b)):
        raise ValueError("Checkout, policy, trusted and host evidence overlap")
    if (not (root / ".git").is_dir() or (root / ".git").is_symlink()
            or not (controller / ".git").is_dir()):
        raise ValueError("Standalone checkouts required")
    if git(root, "rev-parse", "HEAD") != sha or git(root, "status", "--porcelain"):
        raise ValueError("Candidate is not pinned or clean")
    if git(root, "rev-parse", base) != base:
        raise ValueError("Missing base")
    if subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor",
                       base, sha], capture_output=True, timeout=15).returncode != 0:
        raise ValueError("Base SHA is not an ancestor")
    if git(controller, "status", "--porcelain"):
        raise ValueError("Supervisor checkout must be clean and pinned")
    for file in POLICY_FILES:
        source = controller / "scripts" / file
        target = trusted / file
        if target.is_symlink() or not source.is_file() or not target.is_file():
            raise ValueError("Missing or linked trusted policy")
        if _sha256(source) != _sha256(target):
            raise ValueError("Trusted policy differs from reviewed checkout: " + file)
    if dest.is_symlink() or dest.stat().st_mode & 0o077:
        raise ValueError("Host evidence directory must be private (0700)")
    return root, controller, trusted, dest


def docker_command(image, checkout, trusted, sha, base, pr, name):
    def mount(path, target):
        if any(ch in str(path) for ch in (",", "\n", "\r")):
            raise ValueError("Unsupported mount path")
        return "--mount=type=bind,source=" + str(path) + ",target=" + target + ",readonly"
    return [
        "docker", "run", "--detach", "--rm", "--pull=never", "--name=" + name,
        "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=512",
        "--memory=6g", "--cpus=4", "--shm-size=512m",
        "--user=999:999", "--workdir=/workspace",
        "--tmpfs=/tmp:rw,exec,nosuid,nodev,size=1073741824,uid=999,gid=999",
        "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=1073741824,uid=999,gid=999,mode=0700",
        "--tmpfs=/run/postgresql:rw,nosuid,nodev,size=16777216,uid=999,gid=999",
        mount(checkout, "/workspace"),
        mount(trusted, "/trusted"),
        "--env=ARVOR_CI_ISOLATED=1",
        "--env=PYTHONDONTWRITEBYTECODE=1", "--env=HOME=/tmp",
        "--env=STUDIO_BROWSER_TESTS=yes",
        "--env=PO_TEST_DATABASE_URL=postgresql://po_test:ephemeral_ci_only@127.0.0.1:5432/po_test",
        "--env=TRACE_TEST_DATABASE_URL=postgresql://po_test:ephemeral_ci_only@127.0.0.1:5432/po_test",
        "--env=PO_ALLOW_TEST_MIGRATION=yes",
        image, "/bin/sh", "/trusted/arvor_ci_supervised_entrypoint.sh",
    ]


def inspect_isolation(container, checkout, trusted, image, *, run=call):
    data = json.loads(run(["docker", "inspect", container]))
    if not isinstance(data, list) or len(data) != 1:
        raise ValueError("Unexpected docker inspect result")
    obj = data[0]
    host = obj["HostConfig"]
    config = obj["Config"]
    if (obj["Image"] != image or host["NetworkMode"] != "none"
            or host["ReadonlyRootfs"] is not True
            or "ALL" not in [x.upper() for x in (host.get("CapDrop") or [])]
            or "no-new-privileges" not in (host.get("SecurityOpt") or [])
            or str(config["User"]) != "999:999"):
        raise ValueError("Docker isolation differs from approved policy")
    mounts = obj.get("Mounts", [])
    binds = {m["Destination"]: m for m in mounts if m["Type"] == "bind"}
    if set(binds) != {"/workspace", "/trusted"}:
        raise ValueError("Unapproved Docker bind mount")
    for dst, expected in (("/workspace", checkout), ("/trusted", trusted)):
        mount = binds[dst]
        if (Path(mount["Source"]).resolve() != expected
                or mount.get("RW") is not False):
            raise ValueError("Candidate/trusted bind must be readonly")
    if any(m.get("Destination") == "/evidence" for m in mounts):
        raise ValueError("Evidence must not be visible inside sandbox")
    return True


def _check_gate(name, proc, log):
    if name.startswith("regression_"):
        counts = regression_counts(log)
        return bool(proc.returncode == 0 and counts and counts["tests"] > 0
                    and all(counts.get(k) == 0 for k in ("failures", "errors", "skipped"))), counts
    if name == "browser":
        counts = browser_counts(log)
        return bool(proc.returncode == 0 and counts and counts["tests"] > 0), counts
    if name == "dependencies":
        status = audit_diagnostic(log, proc.returncode)
        return proc.returncode == 0 and status == "OK", status
    if name == "video_75":
        return proc.returncode == 0 and video_proof(log), None
    return proc.returncode == 0, None


def execute(image, checkout, trusted, evidence, sha, base, pr, *, run=subprocess.run):
    root, controller, code, out = validate_inputs(
        image, checkout, trusted, evidence, sha, base, pr)
    controller_sha = git(controller, "rev-parse", "HEAD")
    name = "arvor-host-ci-" + uuid4().hex
    command = docker_command(image, root, code, sha, base, pr, name)
    run_id = str(uuid4())
    receipt = {
        "schema": "arvor-local-ci-v1", "run_id": run_id,
        "repo": REPO, "pr": pr, "sha": sha, "base_sha": base,
        "started_at": now(), "finished_at": None,
        "source": "isolated-local-tests", "status": "failure", "gates": [],
        "host_supervision": {
            "version": 1, "controller_sha": controller_sha,
            "image_id": image,
            "controller_files_sha256": {
                fn: _sha256(code / fn) for fn in POLICY_FILES
            },
            "host_observed_docker_exit_codes": True,
            "evidence_not_mounted": True,
            "docker_isolation_inspected": False,
            "independent_execution_provenance_certified": False,
        },
    }
    container = None
    try:
        result = run(command, capture_output=True, text=True, timeout=45, check=False)
        if result.returncode or not re.fullmatch(r"[a-f0-9]{64}", result.stdout.strip()):
            raise ValueError("Docker sandbox failed to start")
        container = result.stdout.strip()
        inspect_isolation(container, root, code, image)
        receipt["host_supervision"]["docker_isolation_inspected"] = True
        # Observe PG readiness from the HOST, not from a PR-supplied receipt.
        for _ in range(30):
            ready = run(["docker", "exec", container, "pg_isready",
                         "-h", "127.0.0.1", "-U", "po_test", "-d", "po_test"],
                        capture_output=True, text=True, timeout=8, check=False)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise ValueError("Disposable PostgreSQL did not become ready")
        for gate in GATES:
            argv = [
                "docker", "exec", "--user=999:999", "--workdir=/workspace",
                container, "/opt/arvor/py314/bin/python",
                "/trusted/arvor_ci_gate.py", "--gate", gate, "--base-sha", base
            ]
            try:
                proc = run(argv, capture_output=True, text=True,
                           timeout=1200, check=False)
                output = (proc.stdout or "") + "\n" + (proc.stderr or "")
                code_rc = proc.returncode
            except subprocess.TimeoutExpired:
                output = "HOST: gate timed out\n"
                code_rc = 124
            log_file = out / (run_id + "-" + gate + ".log")
            with log_file.open("x", encoding="utf-8") as stream:
                stream.write(output)
            log_file.chmod(0o600)
            stub = type("Return", (), {"returncode": code_rc})()
            passed, details = _check_gate(gate, stub, output)
            item = {
                "name": gate, "passed": bool(passed), "returncode": code_rc,
                "log_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
                "tests": details if isinstance(details, dict) else None,
            }
            if gate == "dependencies":
                item["diagnostic_status"] = details
            receipt["gates"].append(item)
            print(gate + ": " + ("OK" if passed else "KO"), flush=True)
            if not passed:
                break
    finally:
        if container:
            stopped = run(["docker", "stop", "--time=5", container],
                          capture_output=True, text=True, timeout=20,
                          check=False)
            if stopped.returncode != 0:
                receipt["host_supervision"]["docker_cleanup_failed"] = True
        receipt["finished_at"] = now()
        receipt["status"] = (
            "success" if (len(receipt["gates"]) == len(GATES)
                          and all(g["passed"] for g in receipt["gates"])
                          and not receipt["host_supervision"].get("docker_cleanup_failed"))
            else "failure"
        )
        if git(root, "rev-parse", "HEAD") != sha or git(root, "status", "--porcelain"):
            receipt["status"] = "failure"
            receipt["checkout_changed"] = True
        with (out / (run_id + ".json")).open("x", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
        (out / (run_id + ".json")).chmod(0o600)
        print(json.dumps({
            "receipt": str(out / (run_id + ".json")),
            "status": receipt["status"], "sha": sha, "run_id": run_id,
            "host_observed": True, "provenance_certified": False,
        }), flush=True)
    return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image-id", required=True)
    p.add_argument("--checkout", required=True, type=Path)
    p.add_argument("--trusted", required=True, type=Path)
    p.add_argument("--evidence", required=True, type=Path)
    p.add_argument("--sha", required=True)
    p.add_argument("--base-sha", required=True)
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--execute", action="store_true")
    a = p.parse_args()
    try:
        roots = validate_inputs(
            a.image_id, a.checkout, a.trusted, a.evidence,
            a.sha, a.base_sha, a.pr)
        if not a.execute:
            print(json.dumps({
                "mode": "dry-run", "host_provenance_design": "docker-exec",
                "image": a.image_id, "sha": a.sha, "pr": a.pr,
                "host_evidence": str(roots[3]),
                "no_evidence_mount": True,
            }))
            return 0
        receipt = execute(
            a.image_id, a.checkout, a.trusted,
            a.evidence, a.sha, a.base_sha, a.pr)
        return 0 if receipt["status"] == "success" else 1
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.SubprocessError) as exc:
        print("HOST SUPERVISOR BLOCKED: " + type(exc).__name__
              + " (" + str(exc)[:180] + ")", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
