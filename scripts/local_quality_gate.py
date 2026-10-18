"""Deterministic, LLM-independent local QA; disposable Postgres only.

The runner's receipt is ephemeral and NOT a cryptographic attestation.
A fresh gate is executed by the same self-hosted CD job before any installation.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

REQUIRED = ("policy", "deps", "secrets", "syntax-js", "syntax-py", "unittest", "sql-benchmark")
SHA = re.compile(r"[0-9a-f]{40}\Z")


def validate_test_database() -> None:
    url = os.getenv("PO_TEST_DATABASE_URL", "")
    trace = os.getenv("TRACE_TEST_DATABASE_URL", "")
    business = os.getenv("PO_DATABASE_URL", "")
    parsed = urlsplit(url)
    if (parsed.scheme not in ("postgresql", "postgres")
        or parsed.hostname not in ("localhost", "127.0.0.1")
        or parsed.username != "po_test"
        or parsed.password != "ephemeral_ci_only"
        or parsed.path != "/po_test"
        or parsed.port is None
        or parsed.query or parsed.fragment
        or trace != url or url == business
        or os.getenv("PO_ALLOW_TEST_MIGRATION") != "yes"):
        raise RuntimeError("Dedicated disposable PostgreSQL test database required")


def assert_receipt(sha: str, path: Path, *, run_id: str, runner_temp: Path) -> None:
    if not SHA.fullmatch(sha) or not run_id or run_id == "local":
        raise RuntimeError("Invalid deployment quality identity")
    temp = runner_temp.resolve(strict=True)
    if (not path.is_absolute() or path.is_symlink()
        or path.parent.resolve(strict=True) != temp
        or path.name != "arvor-quality-" + sha + ".json"):
        raise RuntimeError("Quality receipt must be in runner temporary directory")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (data.get("sha") != sha
        or data.get("run_id") != run_id
        or data.get("source") != "self-hosted-runner"
        or data.get("status") != "passed"
        or data.get("checks") != list(REQUIRED)):
        raise RuntimeError("Incomplete, stale or mismatched local quality receipt")


def execute(sha: str, report: Path, *, cwd: Path) -> None:
    if not SHA.fullmatch(sha):
        raise ValueError("Exact commit SHA required")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=cwd, text=True).strip() != sha:
        raise RuntimeError("Checkout does not match required SHA")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=cwd, text=True).strip():
        raise RuntimeError("Tracked checkout must be clean")
    validate_test_database()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    log = report.parent / ("arvor-quality-" + sha + ".log")
    log.unlink(missing_ok=True)
    log.touch(mode=0o600)
    python = sys.executable
    checks = {
        "policy": [python, "scripts/ci_policy.py"],
        "deps": [python, "-m", "pip_audit", "-r", "requirements.txt", "--progress-spinner", "off"],
        "secrets": ["gitleaks", "git", "--no-banner", "--redact", "--exit-code", "1", "--log-opts=--all", "."],
        "syntax-js": ["sh", "-c", "node --check apps/web/studio.js && node --check apps/web/arvor_reference.js && node --check apps/web/arvor_next.js"],
        "syntax-py": [python, "-m", "py_compile", "apps/api/studio.py"],
        "unittest": [python, "scripts/run_regression.py"],
        "sql-benchmark": [python, "scripts/benchmark_editorial_sql.py", "--rows", "1200", "--disposable"],
    }
    for name, argv in checks.items():
        print("QA local:", name, flush=True)
        try:
            result = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, timeout=1200,
                                    check=False, text=True)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError("Local quality gate blocked at " + name) from error
        with log.open("a", encoding="utf-8") as sink:
            sink.write("\n== " + name + " ==\n" + result.stdout)
        if result.returncode != 0:
            raise RuntimeError("Local quality gate failed at " + name + " (see private runner log)")
    report_data = {
        "sha": sha, "run_id": os.getenv("GITHUB_RUN_ID", "local"),
        "source": "self-hosted-runner" if os.getenv("GITHUB_ACTIONS") == "true" else "local-manual",
        "status": "passed", "checks": list(REQUIRED),
    }
    with report.open("x", encoding="utf-8") as output:
        json.dump(report_data, output, sort_keys=True)
        output.write("\n")
    report.chmod(0o600)
    print("QA local: PASS, SHA=" + sha)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        execute(args.sha, args.report, cwd=Path(__file__).resolve().parents[1])
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as error:
        print("QA local: BLOCKED (" + type(error).__name__ + ")", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
