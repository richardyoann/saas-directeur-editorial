"""Trusted host-side executor specification for an isolated Arvor CI test container.

Invoke only from an approved pinned installation, never from the PR itself.
Does not sign, publish, merge or deploy.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

SHA = re.compile(r"[0-9a-f]{40}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")


def build_docker_command(image_id, checkout, trusted, evidence, sha, base_sha, pr):
    if not IMAGE_ID.fullmatch(image_id):
        raise ValueError("Immutable sha256 image ID required")
    if not SHA.fullmatch(sha) or not SHA.fullmatch(base_sha) or type(pr) is not int or pr <= 0:
        raise ValueError("Complete SHA and PR number required")
    root = checkout.resolve(strict=True)
    code = trusted.resolve(strict=True)
    out = evidence.resolve(strict=True)
    if not root.is_dir() or not code.is_dir() or not out.is_dir():
        raise ValueError("Paths must be existing directories")
    if any(any(ch in str(p) for ch in (",", "\\n", "\\r")) for p in (root, code, out)):
        raise ValueError("Unsafe Docker mount path")
    if not (root / ".git").is_dir() or (root / ".git").is_symlink():
        raise ValueError("Standalone clone with self-contained git objects required")
    if root == code or code == out or root == out or code.is_relative_to(root) or out.is_relative_to(root):
        raise ValueError("Trusted files and evidence must be outside PR checkout")
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=True, timeout=10)
    if proc.stdout.strip() != sha:
        raise ValueError("Not the approved PR commit")
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=True, timeout=10)
    if dirty.stdout.strip():
        raise ValueError("Candidate checkout not clean")
    return [
        "docker", "run", "--rm", "--pull=never",
        "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges", "--pids-limit=512", "--memory=6g", "--cpus=4",
        "--user=999:999", "--workdir=/workspace",
        "--tmpfs=/tmp:rw,exec,nosuid,nodev,size=1073741824,uid=999,gid=999",
        "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=1073741824,uid=999,gid=999,mode=0700",
        "--tmpfs=/run/postgresql:rw,nosuid,nodev,size=16777216,uid=999,gid=999",
        "--mount=type=bind,source=" + str(root) + ",target=/workspace,readonly",
        "--mount=type=bind,source=" + str(code) + ",target=/trusted,readonly",
        "--mount=type=bind,source=" + str(out) + ",target=/evidence",
        "--env=ARVOR_CI_ISOLATED=1", "--env=PYTHONDONTWRITEBYTECODE=1", "--env=HOME=/tmp",
        image_id, "/trusted/arvor_ci_entrypoint.sh", sha, base_sha, str(pr)
    ]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--image-id", required=True, help="Pinned local Docker sha256 image ID")
    p.add_argument("--checkout", type=Path, required=True)
    p.add_argument("--trusted", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--base-sha", required=True)
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--execute", action="store_true", help="Actually launch sandbox; default is validation only")
    a = p.parse_args()
    try:
        command = build_docker_command(a.image_id, a.checkout, a.trusted, a.evidence, a.sha, a.base_sha, a.pr)
        if not a.execute:
            print(json.dumps({"mode": "dry-run", "isolation": "docker-network-none-read-only", "sha": a.sha, "pr": a.pr}))
            return 0
        rc = subprocess.run(command, check=False, timeout=3600).returncode
        print(json.dumps({"mode": "sandbox-executed", "returncode": rc, "sha": a.sha, "pr": a.pr}))
        return rc
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print("BLOCKED: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
