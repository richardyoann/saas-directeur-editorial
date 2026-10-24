"""Read-only, independent consistency check for local-CI evidence.

Runs OUTSIDE the untrusted candidate sandbox. This verifies report/log integrity,
not the provenance of logs that the candidate may itself have been able to edit.
No signing, network requests, status publication, merge or deployment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

from scripts.arvor_ci_attestation import validate
from scripts.arvor_local_ci import GATES, regression_counts, browser_counts

MAX_BYTES = 40 * 1024 * 1024


def read_regular(path):
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        identity = os.fstat(stream.fileno())
        if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
            raise ValueError("Evidence is not a dedicated regular file")
        if identity.st_size > MAX_BYTES:
            raise ValueError("Evidence file exceeds size limit")
        data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Evidence file exceeds size limit")
        return data


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, timeout=20
    ).strip()


def video_proof(log):
    for line in reversed(log.splitlines()):
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("verified") is True:
            return (obj.get("synthetic") is True
                    and obj.get("video_duration_seconds") == 75
                    and obj.get("resolution") == "720x1280"
                    and obj.get("ffprobe") == "passed"
                    and obj.get("data_mutation") is False)
    return False


def verify_receipt(receipt_file, evidence_dir, checkout, expected_sha, base_sha, pr, *, include_validated_receipt=False):
    """Check SHA, Git state, log digests, counts, and video data; return summary."""
    evidence_dir = Path(evidence_dir).resolve(strict=True)
    checkout = Path(checkout).resolve(strict=True)
    receipt_file = Path(receipt_file)
    if not evidence_dir.is_dir() or not checkout.is_dir():
        raise ValueError("Expected evidence directory and checkout")
    if receipt_file.parent.resolve(strict=True) != evidence_dir:
        raise ValueError("Receipt must be in the private evidence directory")

    receipt_bytes = read_regular(receipt_file)
    receipt = validate(json.loads(receipt_bytes))
    if (receipt["status"] != "success" or len(receipt["gates"]) != len(GATES)
            or receipt["sha"] != expected_sha or receipt["base_sha"] != base_sha
            or receipt["pr"] != pr):
        raise ValueError("Unexpected failure or receipt identity")
    if receipt_file.name != receipt["run_id"] + ".json":
        raise ValueError("Receipt filename does not match run id")

    if git(checkout, "rev-parse", "HEAD") != expected_sha:
        raise ValueError("Checkout HEAD differs from receipt")
    if git(checkout, "status", "--porcelain"):
        raise ValueError("Candidate checkout changed")
    if git(checkout, "rev-parse", base_sha) != base_sha:
        raise ValueError("Base commit missing")
    result = subprocess.run(
        ["git", "-C", str(checkout), "merge-base", "--is-ancestor",
         base_sha, expected_sha], check=False, timeout=20,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    if result.returncode != 0:
        raise ValueError("Base is not an ancestor of candidate")

    checked = []
    for gate in receipt["gates"]:
        if not gate["passed"] or gate["returncode"] != 0:
            raise ValueError("Failed gate cannot be integrity approved")
        name = gate["name"]
        log_file = evidence_dir / (receipt["run_id"] + "-" + name + ".log")
        raw = read_regular(log_file)
        if hashlib.sha256(raw).hexdigest() != gate["log_sha256"]:
            raise ValueError("Log digest mismatch for " + name)
        log = raw.decode("utf-8")
        if name.startswith("regression_"):
            counts = regression_counts(log)
            if counts != gate.get("tests"):
                raise ValueError("Regression counters mismatch: " + name)
        elif name == "browser":
            counts = browser_counts(log)
            if counts != gate.get("tests"):
                raise ValueError("Browser counters mismatch")
        elif name == "dependencies":
            if log.splitlines().count("ARVOR_AUDIT_STATUS=OK") != 1:
                raise ValueError("Dependency audit OK marker missing or repeated")
        elif name == "video_75" and not video_proof(log):
            raise ValueError("Video proof missing or inconsistent")
        checked.append(name)
    summary = {
        "status": "log-integrity-verified",
        "sha": receipt["sha"],
        "base_sha": receipt["base_sha"],
        "pr": receipt["pr"],
        "run_id": receipt["run_id"],
        "verified_logs": len(checked),
        "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "independent_execution_provenance_verified": False,
        "attestation_signed": False,
        "merge_or_deploy_authorized": False,
    }
    # For signing, return the very same parsed object whose bytes, identity,
    # hashes and constraints were validated; NEVER re-read the candidate file.
    return (summary, receipt) if include_validated_receipt else summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--pr", required=True, type=int)
    args = parser.parse_args()
    try:
        result = verify_receipt(args.receipt, args.evidence_dir,
                                args.checkout, args.sha, args.base_sha, args.pr)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, UnicodeError,
            subprocess.SubprocessError) as exc:
        print("Evidence verification BLOCKED: " + type(exc).__name__,
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
