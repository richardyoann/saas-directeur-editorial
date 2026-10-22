"""Deterministic SHA-pinned quality gates. Execute ONLY in a disposable isolated sandbox.

No GitHub/Slack credentials and no access to the business database belong here.
Output is unsigned evidence; a separate trusted operator signs and publishes it.
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
from urllib.parse import urlsplit
from uuid import uuid4

SHA = re.compile(r"[0-9a-f]{40}\Z")
GATES = ("db_prepare_312", "regression_312", "sql_benchmark_312",
         "db_prepare_314", "regression_314", "sql_benchmark_314",
         "syntax_js", "syntax_js_reference", "syntax_js_next", "syntax_py", "browser", "dependencies", "secrets",
         "supply_chain", "risk_review", "video_75")


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True, timeout=20).strip()


def validate_db(env):
    url = env.get("PO_TEST_DATABASE_URL", "")
    trace = env.get("TRACE_TEST_DATABASE_URL", "")
    p = urlsplit(url)
    if (p.scheme not in ("postgres", "postgresql") or p.hostname not in ("127.0.0.1", "localhost")
            or not p.port or p.username != "po_test" or p.password != "ephemeral_ci_only"
            or p.path != "/po_test" or p.query or p.fragment or trace != url
            or env.get("PO_ALLOW_TEST_MIGRATION") != "yes" or url == env.get("PO_DATABASE_URL")):
        raise ValueError("Disposable PostgreSQL credentials/identity required")
    prod = urlsplit(env.get("PO_DATABASE_URL", ""))
    if prod.hostname in ("127.0.0.1", "localhost") and (prod.port, prod.path) == (p.port, p.path):
        raise ValueError("Test database collides with business database")


def regression_counts(log):
    for line in reversed(log.splitlines()):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and set(("tests", "failures", "errors", "skipped")) <= set(obj):
            if all(isinstance(obj[k], int) and not isinstance(obj[k], bool) for k in ("tests", "failures", "errors", "skipped")):
                return obj
    return None


def browser_counts(log):
    matches = re.findall(r"Ran (\d+) tests? in", log)
    if not matches or re.search(r"\bskipped=\d+", log) or not re.search(r"(?m)^OK\s*$", log):
        return None
    return {"tests": int(matches[-1]), "failures": 0, "errors": 0, "skipped": 0}


def commands(p312, p314, base):
    def py(version, *argv):
        return [str(p312 if version == 312 else p314), *argv]
    return {
        "db_prepare_312": py(312, "scripts/prepare_test_database.py"),
        "regression_312": py(312, "scripts/run_regression.py"),
        "sql_benchmark_312": py(312, "scripts/benchmark_editorial_sql.py", "--rows", "1200", "--disposable"),
        "db_prepare_314": py(314, "scripts/prepare_test_database.py"),
        "regression_314": py(314, "scripts/run_regression.py"),
        "sql_benchmark_314": py(314, "scripts/benchmark_editorial_sql.py", "--rows", "1200", "--disposable"),
        "syntax_js": ["node", "--check", "apps/web/studio.js"],
        "syntax_js_reference": ["node", "--check", "apps/web/arvor_reference.js"],
        "syntax_js_next": ["node", "--check", "apps/web/arvor_next.js"],
        "syntax_py": py(314, "-m", "py_compile", "apps/api/studio.py"),
        "browser": py(312, "-m", "unittest", "discover", "-s", "browser_checks", "-p", "test_studio_browser.py", "-v"),
        "dependencies": py(312, "-m", "pip_audit", "-r", "requirements.txt", "--progress-spinner", "off"),
        "secrets": ["gitleaks", "git", "--no-banner", "--redact", "--exit-code", "1", "--log-opts=" + base + "..HEAD", "."],
        "supply_chain": py(314, "scripts/ci_policy.py"),
        "risk_review": py(314, "scripts/ci_autonomy.py", "--base", base, "--head", "HEAD"),
        "video_75": py(314, "-m", "scripts.smoke_video_75"),
    }


def execute(root, sha, base_sha, pr, repo, python312, python314, output, *, env=None, run_command=subprocess.run):
    env = dict(os.environ if env is None else env)
    if not SHA.fullmatch(sha) or not SHA.fullmatch(base_sha) or pr <= 0 or repo != "richardyoann/saas-directeur-editorial":
        raise ValueError("Invalid CI identity")
    if env.get("ARVOR_CI_ISOLATED") != "1":
        raise ValueError("Isolated execution confirmation missing (not proof of isolation)")
    validate_db(env)
    if git(root, "rev-parse", "HEAD") != sha or git(root, "status", "--porcelain"):
        raise ValueError("Wrong or dirty candidate checkout")
    if git(root, "rev-parse", base_sha) != base_sha:
        raise ValueError("Unknown base SHA")
    if subprocess.run(["git", "merge-base", "--is-ancestor", base_sha, sha], cwd=root,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode != 0:
        raise ValueError("The attested base is not an ancestor of HEAD")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.chmod(0o700)
    run_id = str(uuid4())
    receipt = {"schema": "arvor-local-ci-v1", "run_id": run_id, "repo": repo, "pr": pr,
               "sha": sha, "base_sha": base_sha, "started_at": utcnow(), "finished_at": None,
               "source": "isolated-local-tests", "gates": [], "status": "failure"}
    clean_env = {k: env[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "PO_TEST_DATABASE_URL", "TRACE_TEST_DATABASE_URL", "PO_ALLOW_TEST_MIGRATION") if k in env}
    clean_env["STUDIO_BROWSER_TESTS"] = "yes"
    for name, argv in commands(python312, python314, base_sha).items():
        result = {"name": name, "passed": False, "returncode": None, "tests": None, "log_sha256": None}
        log = output / (run_id + "-" + name + ".log")
        try:
            proc = run_command(argv, cwd=root, env=clean_env, capture_output=True, text=True, timeout=1200, check=False)
            output_text = (proc.stdout or "") + "\n" + (proc.stderr or "")
            log.write_text(output_text, encoding="utf-8")
            log.chmod(0o600)
            result["log_sha256"] = hashlib.sha256(output_text.encode()).hexdigest()
            result["returncode"] = proc.returncode
            counts = regression_counts(output_text) if name.startswith("regression_") else browser_counts(output_text) if name == "browser" else None
            if name == "video_75":
                try:
                    video = next((json.loads(line) for line in reversed(output_text.splitlines())
                                  if line.strip().startswith("{") and "\"verified\"" in line), None)
                except ValueError:
                    video = None
                result["passed"] = (proc.returncode == 0 and isinstance(video, dict)
                                    and video.get("verified") is True
                                    and video.get("synthetic") is True
                                    and video.get("video_duration_seconds") == 75
                                    and video.get("resolution") == "720x1280"
                                    and video.get("ffprobe") == "passed")
            if name.startswith("regression_") or name == "browser":
                result["tests"] = counts
                result["passed"] = proc.returncode == 0 and counts is not None and counts["tests"] > 0 and all(counts[k] == 0 for k in ("failures", "errors", "skipped"))
            else:
                result["passed"] = proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired, UnicodeError):
            result["error"] = "process_unavailable_or_timeout"
        receipt["gates"].append(result)
        if not result["passed"]:
            break
    receipt["finished_at"] = utcnow()
    receipt["status"] = "success" if len(receipt["gates"]) == len(GATES) and all(g["passed"] for g in receipt["gates"]) else "failure"
    if git(root, "rev-parse", "HEAD") != sha or git(root, "status", "--porcelain"):
        receipt["status"] = "failure"
        receipt["checkout_changed"] = True
    destination = output / (run_id + ".json")
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2)
    destination.chmod(0o600)
    return destination, receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkout", required=True, type=Path)
    p.add_argument("--sha", required=True)
    p.add_argument("--base-sha", required=True)
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--python312", required=True)
    p.add_argument("--python314", required=True)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    try:
        path, report = execute(a.checkout, a.sha, a.base_sha, a.pr, "richardyoann/saas-directeur-editorial", a.python312, a.python314, a.output)
        print(json.dumps({"receipt": str(path), "status": report["status"], "sha": a.sha}))
        return 0 if report["status"] == "success" else 1
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("BLOCKED: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
