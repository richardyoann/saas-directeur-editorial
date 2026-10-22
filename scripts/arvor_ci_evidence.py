"""Trusted-side local CI evidence: SHA-bound, fail-closed and HMAC authenticated.

The signing key stays OUTSIDE the tested checkout and the test container.  A
signature proves who sealed a report, not that a human approved a PR.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
from datetime import datetime, timezone

SHA = re.compile(r"[0-9a-f]{40}\Z")
GATES = (
    "regression_312", "regression_314", "sql_benchmark", "js_syntax",
    "browser", "dependency_audit", "secret_scan", "supply_chain", "video_75",
)
TEST_GATES = frozenset(("regression_312", "regression_314", "browser"))


def canonical(data):
    return json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def validate_report(report, expected_sha):
    if not isinstance(report, dict) or set(report) != {
        "schema", "repository", "sha", "base_sha", "run_id", "created_at",
        "environment", "gates", "human_review", "deployment",
    }:
        raise ValueError("invalid evidence schema")
    if report["schema"] != "arvor-local-ci-v1" or report["repository"] != "richardyoann/saas-directeur-editorial":
        raise ValueError("unexpected repository or schema")
    if not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha) or report["sha"] != expected_sha:
        raise ValueError("SHA mismatch")
    if not isinstance(report["base_sha"], str) or not SHA.fullmatch(report["base_sha"]):
        raise ValueError("invalid base SHA")
    if not isinstance(report["run_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{12,96}", report["run_id"]):
        raise ValueError("invalid run ID")
    timestamp = datetime.fromisoformat(report["created_at"].replace("Z", "+00:00"))
    if not timestamp.tzinfo or abs((datetime.now(timezone.utc) - timestamp).total_seconds()) > 86400:
        raise ValueError("stale or invalid timestamp")
    if report["environment"] != "isolated-no-secrets" or report["human_review"] != "required" or report["deployment"] != "not_performed":
        raise ValueError("unsafe evidence claims")
    gates = report["gates"]
    if not isinstance(gates, dict) or set(gates) != set(GATES):
        raise ValueError("missing or extra gate")
    for name, gate in gates.items():
        if not isinstance(gate, dict) or set(gate) != {"status", "exit_code", "tests", "skipped"}:
            raise ValueError("invalid gate: " + name)
        if gate["status"] not in {"passed", "failed", "blocked"} or type(gate["exit_code"]) is not int:
            raise ValueError("invalid gate result")
        if type(gate["tests"]) is not int or type(gate["skipped"]) is not int or gate["tests"] < 0 or gate["skipped"] < 0:
            raise ValueError("invalid test counts")
        if gate["status"] == "passed" and (gate["exit_code"] != 0 or gate["skipped"] != 0):
            raise ValueError("false passing gate")
        if name in TEST_GATES and gate["status"] == "passed" and gate["tests"] < 1:
            raise ValueError("no tests executed")
    return all(gate["status"] == "passed" for gate in gates.values())


def key_bytes(key_path):
    path = Path(key_path)
    if path.is_symlink() or not path.is_file() or (path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO)):
        raise ValueError("HMAC key must be a private regular file (0600)")
    key = path.read_bytes().strip()
    if len(key) < 32:
        raise ValueError("key too short")
    return key


def seal(report, expected_sha, key):
    passed = validate_report(report, expected_sha)
    payload = {"report": report, "passed": passed}
    payload["mac"] = hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()
    return payload


def verify(envelope, expected_sha, key):
    if not isinstance(envelope, dict) or set(envelope) != {"report", "passed", "mac"}:
        raise ValueError("invalid envelope")
    unsigned = {"report": envelope["report"], "passed": envelope["passed"]}
    expected_mac = hmac.new(key, canonical(unsigned), hashlib.sha256).hexdigest()
    if not isinstance(envelope["mac"], str) or not hmac.compare_digest(envelope["mac"], expected_mac):
        raise ValueError("bad signature")
    passed = validate_report(envelope["report"], expected_sha)
    if type(envelope["passed"]) is not bool or envelope["passed"] is not passed:
        raise ValueError("invalid signed verdict")
    return passed
