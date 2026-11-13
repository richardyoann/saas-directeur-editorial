"""Verify host-owned Docker observations and candidate gate evidence.

Run only from the separately reviewed, clean controller checkout. Candidate
code has no access to this process, the host evidence directory, or signing key.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from scripts.arvor_ci_attestation import validate
from scripts.arvor_local_ci import GATES, regression_counts, browser_counts
from scripts.arvor_ci_trust import (
    SANDBOX_POLICY_FILES, POLICY_VERSION, canonical_json, policy_digest, policy_snapshot, validate_docker_inspection,
)

MAX_BYTES = 40 * 1024 * 1024
MAX_EVIDENCE_AGE = timedelta(hours=2)


def read_regular(path):
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        identity = os.fstat(stream.fileno())
        if (not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1
                or identity.st_uid != os.getuid()
                or stat.S_IMODE(identity.st_mode) != 0o600):
            raise ValueError("Evidence must be a host-owned private regular file")
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


def _time(value, label):
    try:
        result = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Malformed " + label + " timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Timezone required for " + label)
    return result.astimezone(timezone.utc)


def _private_directory(path):
    st = path.stat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) != 0o700):
        raise ValueError("Host evidence directory must be owned and mode 0700")


def _verify_host_observation(observation, receipt, *, checkout, trusted,
                             controller, controller_sha, image_id,
                             expected_policy_sha256, now):
    if not isinstance(observation, dict) or observation.get("schema") != "arvor-host-observation-v1":
        raise ValueError("Host observation missing or unsupported")
    expected = {
        "run_id": receipt["run_id"], "repo": receipt["repo"],
        "pr": receipt["pr"], "sha": receipt["sha"],
        "base_sha": receipt["base_sha"], "controller_sha": controller_sha,
        "image_id": image_id, "policy_version": POLICY_VERSION,
    }
    if any(observation.get(k) != v for k, v in expected.items()):
        raise ValueError("Host observation identity mismatch")
    actual_files = policy_snapshot(controller)
    actual_policy = policy_digest(controller)
    if (actual_policy != expected_policy_sha256
            or observation.get("policy_sha256") != actual_policy
            or observation.get("policy_files_sha256") != actual_files):
        raise ValueError("Pinned controller policy digest mismatch")
    for filename in SANDBOX_POLICY_FILES:
        copied = Path(trusted) / filename
        source = Path(controller) / "scripts" / filename
        if (copied.is_symlink() or not copied.is_file()
                or hashlib.sha256(copied.read_bytes()).hexdigest()
                != hashlib.sha256(source.read_bytes()).hexdigest()):
            raise ValueError("Sandbox policy copy differs from pinned controller")
    begin = _time(observation.get("started_at"), "host start")
    end = _time(observation.get("finished_at"), "host finish")
    current = now.astimezone(timezone.utc)
    if (begin > current + timedelta(minutes=2) or end > current + timedelta(minutes=2)
            or begin > end or current - end > MAX_EVIDENCE_AGE):
        raise ValueError("Host evidence is future-dated, reversed, or expired")
    if observation.get("docker_stop_returncode") != 0:
        raise ValueError("Docker cleanup was not observed successful")

    inspect = observation.get("docker_inspect")
    if not isinstance(inspect, dict):
        raise ValueError("Host Docker inspection missing")
    validate_docker_inspection(inspect, checkout, trusted, image_id)
    if inspect.get("Id") != observation.get("container_id"):
        raise ValueError("Container identity mismatch")

    executions = observation.get("gate_exec_observations")
    gates = receipt.get("gates")
    if (not isinstance(executions, list) or len(executions) != len(GATES)
            or len(gates) != len(GATES)):
        raise ValueError("Missing host-observed gates")
    for expected_name, host_gate, gate in zip(GATES, executions, gates, strict=True):
        expected_argv = [
            "docker", "exec", "--user=999:999", "--workdir=/workspace",
            observation.get("container_id"), "/opt/arvor/py314/bin/python",
            "/trusted/arvor_ci_gate.py", "--gate", expected_name,
            "--base-sha", receipt["base_sha"],
        ]
        command_digest = hashlib.sha256(canonical_json(expected_argv)).hexdigest()
        if (not isinstance(host_gate, dict) or host_gate.get("name") != expected_name
                or gate.get("name") != expected_name
                or host_gate.get("docker_exec_returncode") != 0
                or gate.get("returncode") != host_gate.get("docker_exec_returncode")
                or gate.get("passed") is not True
                or host_gate.get("gate_command_sha256") != command_digest
                or host_gate.get("log_sha256") != gate.get("log_sha256")):
            raise ValueError("Host-observed gate failed or differs: " + expected_name)
    return {
        "schema": "arvor-verified-provenance-v1",
        "controller_sha": controller_sha,
        "policy_version": POLICY_VERSION,
        "policy_sha256": actual_policy,
        "policy_files_sha256": actual_files,
        "image_id": image_id,
        "host_observation_sha256": None,  # caller fills from exact host bytes
        "run_id": receipt["run_id"],
        "verified_at": current.isoformat(),
    }


def verify_receipt(receipt_file, evidence_dir, checkout, expected_sha, base_sha, pr,
                   *, host_observation_file, trusted_policy, trusted_controller,
                   controller_sha, expected_image_id, expected_policy_sha256, now=None,
                   include_validated_receipt=False):
    """Verify identity, logs and host-observed execution from a pinned controller."""
    now = now or datetime.now(timezone.utc)
    evidence_dir = Path(evidence_dir).resolve(strict=True)
    checkout = Path(checkout).resolve(strict=True)
    controller = Path(trusted_controller).resolve(strict=True)
    trusted = Path(trusted_policy).resolve(strict=True)
    receipt_file = Path(receipt_file)
    host_observation_file = Path(host_observation_file)
    if (Path(evidence_dir).is_symlink() or Path(checkout).is_symlink()
            or Path(trusted_controller).is_symlink() or Path(trusted_policy).is_symlink()
            or not evidence_dir.is_dir() or not checkout.is_dir()
            or not controller.is_dir() or not trusted.is_dir()):
        raise ValueError("Evidence, candidate, policy and controller directories required")
    _private_directory(evidence_dir)
    if receipt_file.parent.resolve(strict=True) != evidence_dir:
        raise ValueError("Receipt must be in private host evidence directory")
    if host_observation_file.parent.resolve(strict=True) != evidence_dir:
        raise ValueError("Host observation must be in private host evidence directory")
    if receipt_file == host_observation_file:
        raise ValueError("Receipt and host observation must be separate files")
    roots = (controller, checkout, evidence_dir, trusted)
    if len(set(roots)) != len(roots) or any(
            a.is_relative_to(b) or b.is_relative_to(a)
            for i, a in enumerate(roots) for b in roots[i + 1:]):
        raise ValueError("Controller, candidate, policy and evidence must be separate")
    if (not re.fullmatch(r"[0-9a-f]{40}", controller_sha)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_image_id)
            or not re.fullmatch(r"[0-9a-f]{64}", expected_policy_sha256)):
        raise ValueError("Exact controller, image and policy pins are required")
    if not Path(__file__).resolve().is_relative_to(controller):
        raise ValueError("Verifier must execute from the pinned controller checkout")
    if git(controller, "rev-parse", "HEAD") != controller_sha or git(controller, "status", "--porcelain"):
        raise ValueError("Controller checkout is not clean and pinned")
    if git(checkout, "rev-parse", "HEAD") != expected_sha:
        raise ValueError("Candidate checkout HEAD differs from expected SHA")
    if git(checkout, "status", "--porcelain"):
        raise ValueError("Candidate checkout changed")
    if git(checkout, "rev-parse", base_sha) != base_sha:
        raise ValueError("Base commit missing")
    result = subprocess.run(
        ["git", "-C", str(checkout), "merge-base", "--is-ancestor", base_sha, expected_sha],
        check=False, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise ValueError("Base is not an ancestor of candidate")

    receipt_bytes = read_regular(receipt_file)
    receipt = validate(json.loads(receipt_bytes))
    if (receipt["status"] != "success" or receipt["repo"] != "richardyoann/saas-directeur-editorial"
            or len(receipt["gates"]) != len(GATES) or receipt["sha"] != expected_sha
            or receipt["base_sha"] != base_sha or receipt["pr"] != pr
            or receipt_file.name != receipt["run_id"] + ".json"):
        raise ValueError("Unexpected receipt identity or failed gates")
    begin = _time(receipt["started_at"], "receipt start")
    end = _time(receipt["finished_at"], "receipt finish")
    current = now.astimezone(timezone.utc)
    if (begin > current + timedelta(minutes=2) or end > current + timedelta(minutes=2)
            or begin > end or current - end > MAX_EVIDENCE_AGE):
        raise ValueError("Receipt is future-dated, reversed, or expired")

    checked = []
    for expected_name, gate in zip(GATES, receipt["gates"], strict=True):
        if (gate.get("name") != expected_name or gate.get("passed") is not True
                or gate.get("returncode") != 0):
            raise ValueError("Gate absent, reordered, skipped, or failed")
        log_file = evidence_dir / (receipt["run_id"] + "-" + expected_name + ".log")
        raw = read_regular(log_file)
        if hashlib.sha256(raw).hexdigest() != gate.get("log_sha256"):
            raise ValueError("Log digest mismatch for " + expected_name)
        log = raw.decode("utf-8")
        if expected_name.startswith("regression_") and regression_counts(log) != gate.get("tests"):
            raise ValueError("Regression counters mismatch: " + expected_name)
        if expected_name == "browser" and browser_counts(log) != gate.get("tests"):
            raise ValueError("Browser counters mismatch")
        if expected_name == "dependencies" and log.splitlines().count("ARVOR_AUDIT_STATUS=OK") != 1:
            raise ValueError("Dependency audit marker missing or repeated")
        if expected_name == "video_75" and not video_proof(log):
            raise ValueError("Video proof missing or inconsistent")
        checked.append(expected_name)

    host_bytes = read_regular(host_observation_file)
    host = json.loads(host_bytes)
    host_digest = hashlib.sha256(host_bytes).hexdigest()
    supervision = receipt.get("host_supervision")
    if not isinstance(supervision, dict) or supervision.get("host_observation_sha256") != host_digest:
        raise ValueError("Host observation digest mismatch")
    provenance = _verify_host_observation(
        host, receipt, checkout=checkout, trusted=trusted,
        controller=controller, controller_sha=controller_sha,
        image_id=expected_image_id, expected_policy_sha256=expected_policy_sha256,
        now=now,
    )
    for field in ("controller_sha", "policy_version", "policy_sha256", "policy_files_sha256", "image_id"):
        if supervision.get(field) != provenance[field]:
            raise ValueError("Receipt host summary mismatch")
    provenance["host_observation_sha256"] = host_digest
    summary = {
        "status": "host-provenance-and-log-integrity-verified",
        "sha": receipt["sha"], "base_sha": receipt["base_sha"],
        "pr": receipt["pr"], "run_id": receipt["run_id"],
        "verified_logs": len(checked),
        "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "host_observation_sha256": host_digest,
        "independent_execution_provenance_verified": True,
        "attestation_signed": False, "merge_or_deploy_authorized": False,
    }
    if include_validated_receipt:
        return summary, receipt, provenance
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--host-observation", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--trusted-controller", required=True, type=Path)
    parser.add_argument("--trusted-policy", required=True, type=Path)
    parser.add_argument("--controller-sha", required=True)
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--policy-sha256", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--pr", required=True, type=int)
    args = parser.parse_args()
    try:
        result = verify_receipt(
            args.receipt, args.evidence_dir, args.checkout,
            args.sha, args.base_sha, args.pr,
            host_observation_file=args.host_observation,
            trusted_controller=args.trusted_controller,
            trusted_policy=args.trusted_policy,
            controller_sha=args.controller_sha,
            expected_image_id=args.image_id,
            expected_policy_sha256=args.policy_sha256,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, UnicodeError,
            subprocess.SubprocessError) as exc:
        print("Evidence verification BLOCKED: " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
