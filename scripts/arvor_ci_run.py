"""Trusted local CI controller. Run from a trusted checkout, NOT from a PR.

Tests execute in disposable, secretless containers; no Docker socket is ever
mounted into a test container. Signing and publishing are separate operations.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

try:
    from scripts.arvor_ci_evidence import GATES, SHA
except ModuleNotFoundError:
    from arvor_ci_evidence import GATES, SHA

IMAGES = {"3.12": "arvor-ci:3.12", "3.14": "arvor-ci:3.14"}
DB_URL = "postgresql://po_test:ephemeral_ci_only@localhost:5432/po_test"


def cmd(args, *, timeout=1200, cwd=None):
    return subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout, check=False)


def ensure_target(target, sha, base):
    if not SHA.fullmatch(sha) or not SHA.fullmatch(base):
        raise ValueError("exact full SHAs required")
    target = target.resolve(strict=True)
    head = cmd(["git", "rev-parse", "HEAD"], cwd=target, timeout=20)
    status = cmd(["git", "status", "--porcelain"], cwd=target, timeout=20)
    ancestor = cmd(["git", "merge-base", "--is-ancestor", base, sha], cwd=target, timeout=20)
    if head.returncode or head.stdout.strip() != sha or status.returncode or status.stdout.strip() or ancestor.returncode:
        raise RuntimeError("dirty, stale or unrelated target checkout")
    if not (target / "requirements.txt").is_file():
        raise RuntimeError("requirements missing")
    return target


def docker_gate(target, gate, container, *, needs_db=False, online=False):
    if online and needs_db:
        raise ValueError("DB must never be on an online test network")
    network = "bridge" if online else "none"
    db_name = None
    if needs_db:
        db_name = "arvor-ci-db-" + secrets.token_hex(6)
        started = cmd(["docker", "run", "--pull=never", "-d", "--network", "none", "--name", db_name,
                       "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,nodev,size=512m",
                       "-e", "POSTGRES_USER=po_test", "-e", "POSTGRES_PASSWORD=ephemeral_ci_only",
                       "-e", "POSTGRES_DB=po_test", "postgres:16"], timeout=60)
        if started.returncode:
            return (2, "disposable PostgreSQL did not start")
        network = "container:" + db_name
    try:
        if db_name:
            for _ in range(35):
                ready = cmd(["docker", "exec", db_name, "pg_isready", "-U", "po_test", "-d", "po_test"], timeout=10)
                if ready.returncode == 0:
                    break
                import time
                time.sleep(1)
            else:
                return (2, "disposable PostgreSQL not ready")
        image, argv = container
        docker = ["docker", "run", "--rm", "--pull=never", "--read-only", "--cap-drop=ALL",
                  "--security-opt=no-new-privileges", "--pids-limit=256", "--memory=2g", "--cpus=4",
                  "--network", network, "--user", "10001:10001", "-v", str(target) + ":/workspace:ro",
                  "--workdir", "/workspace", "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m",
                  "-e", "HOME=/tmp", "-e", "PO_TEST_DATABASE_URL=" + DB_URL,
                  "-e", "TRACE_TEST_DATABASE_URL=" + DB_URL, "-e", "PO_ALLOW_TEST_MIGRATION=yes"]
        if gate == "browser":
            docker.extend(["-e", "STUDIO_BROWSER_TESTS=yes"])
        docker.extend([image, *argv])
        result = cmd(docker, timeout=1200)
        return (result.returncode, result.stdout)
    finally:
        if db_name:
            cmd(["docker", "rm", "-f", db_name], timeout=30)


def run(target, sha, base, output):
    target = ensure_target(target, sha, base)
    if output.exists() or output.is_symlink():
        raise FileExistsError("refusing to overwrite CI evidence")
    docker = cmd(["docker", "version", "--format", "{{.Server.Version}}"], timeout=20)
    images_ok = docker.returncode == 0 and all(cmd(["docker", "image", "inspect", x], timeout=20).returncode == 0 for x in (*IMAGES.values(), "postgres:16"))
    specs = {
        "regression_312": (IMAGES["3.12"], ["sh", "-c", "python scripts/prepare_test_database.py && python scripts/run_regression.py"], True, False),
        "regression_314": (IMAGES["3.14"], ["sh", "-c", "python scripts/prepare_test_database.py && python scripts/run_regression.py"], True, False),
        "sql_benchmark": (IMAGES["3.14"], ["python", "scripts/benchmark_editorial_sql.py", "--rows", "1200", "--disposable"], True, False),
        "js_syntax": (IMAGES["3.14"], ["sh", "-c", "node --check apps/web/studio.js && node --check apps/web/arvor_reference.js && node --check apps/web/arvor_next.js"], False, False),
        "browser": (IMAGES["3.12"], ["python", "-m", "unittest", "discover", "-s", "browser_checks", "-p", "test_studio_browser.py", "-v"], False, False),
        "dependency_audit": (IMAGES["3.14"], ["python", "-m", "pip_audit", "-r", "requirements.txt", "--progress-spinner", "off"], False, True),
        "supply_chain": (IMAGES["3.14"], ["python", "scripts/ci_policy.py"], False, False),
        "video_75": (IMAGES["3.12"], ["python", "-m", "scripts.smoke_video_75"], False, False),
    }
    results = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    log_dir = output.parent / ("logs-" + sha[:12])
    log_dir.mkdir(mode=0o700, exist_ok=True)
    for gate in GATES:
        tests = skipped = 0
        if not images_ok:
            rc, content = 2, "Docker or pinned local CI images unavailable"
        elif gate == "secret_scan":
            # Host-side scanner parses Git data only; it must not execute PR code.
            scan = cmd(["gitleaks", "git", "--no-banner", "--redact", "--exit-code", "1",
                        "--log-opts=" + base + ".." + sha, "."], cwd=target, timeout=120)
            rc, content = scan.returncode, scan.stdout
        else:
            image, argv, db, online = specs[gate]
            try:
                rc, content = docker_gate(target, gate, (image, argv), needs_db=db, online=online)
            except (OSError, subprocess.TimeoutExpired):
                rc, content = 2, "gate unavailable or timed out"
        if gate.startswith("regression_"):
            matches = re.findall(r'\{[^\n]*"tests"\s*:\s*\d+[^\n]*\}', content)
            try:
                last = json.loads(matches[-1])
                tests, skipped = int(last["tests"]), int(last["skipped"])
                if last.get("errors") or last.get("failures"):
                    rc = 1
            except (IndexError, KeyError, ValueError, TypeError):
                rc = 2
        elif gate == "browser":
            match = re.search(r"Ran\s+(\d+)\s+tests?", content)
            tests = int(match.group(1)) if match else 0
            if re.search(r"\bskipped=[1-9]\d*", content):
                skipped = 1
        if gate in ("regression_312", "regression_314", "browser") and tests == 0:
            rc = 2
        status = "passed" if rc == 0 and skipped == 0 else "failed" if rc == 1 else "blocked"
        results[gate] = {"status": status, "exit_code": rc, "tests": tests, "skipped": skipped}
        path = log_dir / (gate + ".log")
        with path.open("x", encoding="utf-8") as file:
            file.write(content[:200000])
        path.chmod(0o600)
        print(gate + ": " + status, flush=True)
    report = {
        "schema": "arvor-local-ci-v1", "repository": "richardyoann/saas-directeur-editorial",
        "sha": sha, "base_sha": base, "run_id": "local-" + secrets.token_hex(12),
        "created_at": datetime.now(timezone.utc).isoformat(), "environment": "isolated-no-secrets",
        "gates": results, "human_review": "required", "deployment": "not_performed",
    }
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, sort_keys=True, indent=2)
        file.write("\n")
    output.chmod(0o600)
    return 0 if all(x["status"] == "passed" for x in results.values()) else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args.target, args.sha, args.base, args.output)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("Local CI refused: " + type(exc).__name__, file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
