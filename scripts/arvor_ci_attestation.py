"""Trusted Ed25519 evidence signing and verification; NEVER run with keys in candidate sandbox."""
import argparse
import base64
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from scripts.arvor_ci_trust import POLICY_VERSION
from scripts.arvor_ci_host_trust import (
    DEFAULT_TRUST_PATH, load_host_trust, verify_host_controller,
    verify_host_key, verify_host_signer, verify_private_key,
)
from scripts.arvor_local_ci import GATES, SHA


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def validate(receipt):
    if not isinstance(receipt, dict) or receipt.get("schema") != "arvor-local-ci-v1":
        raise ValueError("Unsupported evidence schema")
    try:
        UUID(receipt["run_id"])
        if receipt["repo"] != "richardyoann/saas-directeur-editorial" or not isinstance(receipt["pr"], int) or receipt["pr"] <= 0:
            raise ValueError("Wrong target")
        if not SHA.fullmatch(receipt["sha"]) or not SHA.fullmatch(receipt["base_sha"]):
            raise ValueError("Invalid SHA")
        begin = datetime.fromisoformat(receipt["started_at"])
        end = datetime.fromisoformat(receipt["finished_at"])
        if not begin.tzinfo or not end.tzinfo or begin > end:
            raise ValueError("Invalid timestamps")
        if receipt["source"] != "isolated-local-tests" or receipt.get("checkout_changed"):
            raise ValueError("Untrusted environment")
        gates = receipt["gates"]
        if not isinstance(gates, list) or len(gates) > len(GATES):
            raise ValueError("Invalid gate set")
        if [x["name"] for x in gates] != list(GATES[:len(gates)]):
            raise ValueError("Missing/reordered quality gates")
        for g in gates:
            if not isinstance(g["passed"], bool) or not isinstance(g["returncode"], (int, type(None))) or (g["log_sha256"] is not None and not SHA256.fullmatch(g["log_sha256"])):
                raise ValueError("Malformed gate")
            if g["passed"] and (g["returncode"] != 0 or not g["log_sha256"]):
                raise ValueError("Unproven green gate")
            if g["name"].startswith("regression_") or g["name"] == "browser":
                counts = g.get("tests")
                if g["passed"] and (not isinstance(counts, dict) or counts.get("tests", 0) <= 0 or any(counts.get(k) != 0 for k in ("failures", "errors", "skipped"))):
                    raise ValueError("Skipped/failing test disguised as success")
        expected_status = "success" if len(gates) == len(GATES) and all(x["passed"] for x in gates) else "failure"
        if receipt["status"] != expected_status:
            raise ValueError("Inconsistent overall status")
    except (KeyError, TypeError, OverflowError) as e:
        raise ValueError("Malformed receipt") from e
    return receipt


def validate_provenance(receipt, provenance):
    if not isinstance(provenance, dict) or provenance.get("schema") != "arvor-verified-provenance-v1":
        raise ValueError("Independently verified host provenance required")
    supervision = receipt.get("host_supervision")
    required = {
        "controller_sha": supervision.get("controller_sha") if isinstance(supervision, dict) else None,
        "policy_version": POLICY_VERSION,
        "policy_sha256": supervision.get("policy_sha256") if isinstance(supervision, dict) else None,
        "policy_files_sha256": supervision.get("policy_files_sha256") if isinstance(supervision, dict) else None,
        "image_id": supervision.get("image_id") if isinstance(supervision, dict) else None,
        "host_observation_sha256": supervision.get("host_observation_sha256") if isinstance(supervision, dict) else None,
        "run_id": receipt.get("run_id"),
    }
    if not all(required.values()) or any(provenance.get(key) != value for key, value in required.items()):
        raise ValueError("Verified provenance does not match host receipt")
    if not SHA.fullmatch(provenance["controller_sha"]):
        raise ValueError("Invalid pinned controller identity")
    if not SHA256.fullmatch(provenance["policy_sha256"]):
        raise ValueError("Invalid policy identity")
    if not SHA256.fullmatch(provenance["host_observation_sha256"]):
        raise ValueError("Invalid host observation digest")
    if (not isinstance(provenance["policy_files_sha256"], dict)
            or not provenance["policy_files_sha256"]
            or any(not isinstance(k, str) or not SHA256.fullmatch(v)
                   for k, v in provenance["policy_files_sha256"].items())):
        raise ValueError("Invalid policy file identities")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", provenance["image_id"]):
        raise ValueError("Invalid immutable image identity")
    verified_at = datetime.fromisoformat(provenance["verified_at"])
    started = datetime.fromisoformat(receipt["started_at"])
    finished = datetime.fromisoformat(receipt["finished_at"])
    if (not verified_at.tzinfo or not started.tzinfo or not finished.tzinfo
            or verified_at < finished or verified_at > datetime.now(verified_at.tzinfo) + timedelta(minutes=2)):
        raise ValueError("Invalid provenance verification time")
    return provenance


def sign(receipt, private_pem, key_id, provenance):
    validate(receipt)
    provenance = validate_provenance(receipt, provenance)
    key = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", key_id):
        raise ValueError("Invalid signing configuration")
    unsigned = {"algorithm": "Ed25519", "key_id": key_id,
                "evidence": receipt, "provenance": provenance}
    return unsigned | {"signature": base64.b64encode(key.sign(canonical(unsigned))).decode("ascii")}


def verify(envelope, public_pem, key_id):
    fields = {"algorithm", "key_id", "evidence", "provenance", "signature"}
    if (not isinstance(envelope, dict) or set(envelope) != fields
            or envelope["algorithm"] != "Ed25519" or envelope["key_id"] != key_id):
        raise ValueError("Unexpected attestation")
    key = serialization.load_pem_public_key(public_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Not an Ed25519 public key")
    receipt = validate(envelope["evidence"])
    validate_provenance(receipt, envelope["provenance"])
    try:
        signature = base64.b64decode(envelope["signature"], validate=True)
        unsigned = {k: envelope[k] for k in ("algorithm", "key_id", "evidence", "provenance")}
        key.verify(signature, canonical(unsigned))
    except (ValueError, InvalidSignature) as e:
        raise ValueError("Bad attestation signature") from e
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("sign", "verify"))
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--key", type=Path, required=True)
    p.add_argument("--key-id", required=True)
    p.add_argument("--output", type=Path)
    p.add_argument("--evidence-dir", type=Path)
    p.add_argument("--host-observation", type=Path)
    p.add_argument("--checkout", type=Path)
    p.add_argument("--trusted-controller", type=Path)
    p.add_argument("--trusted-policy", type=Path)
    p.add_argument("--controller-sha")
    p.add_argument("--image-id")
    p.add_argument("--policy-sha256")
    p.add_argument("--sha")
    p.add_argument("--base-sha")
    p.add_argument("--pr", type=int)
    a = p.parse_args()
    if a.action == "sign":
        if not a.output or a.output.exists():
            p.error("Fresh --output required")
        if (not a.evidence_dir or not a.checkout or not a.sha
                or not a.base_sha or a.pr is None or not a.host_observation
                or not a.trusted_controller or not a.trusted_policy or not a.controller_sha
                or not a.image_id or not a.policy_sha256):
            p.error("Signing requires host observation and pinned controller/policy/image identity")
        host_trust = load_host_trust(DEFAULT_TRUST_PATH)
        if (a.key.resolve(strict=True) != Path(host_trust["private_key_path"])
                or a.key_id != host_trust["key_id"]
                or a.controller_sha != host_trust["controller_sha"]
                or a.image_id != host_trust["image_id"]
                or a.policy_sha256 != host_trust["policy_sha256"]
                or a.trusted_policy.resolve(strict=True)
                   != Path(host_trust["trusted_policy_path"])):
            raise ValueError("Signing arguments differ from host trust pins")
        verify_host_controller(host_trust, host_trust["controller_path"])
        verify_host_signer(host_trust, __file__)
        verify_host_controller(host_trust, a.trusted_controller)
        # The script and imported policy execute only from the pinned controller checkout.
        from scripts.arvor_ci_evidence_verify import verify_receipt
        verification, checked_receipt, provenance = verify_receipt(
            a.input, a.evidence_dir, a.checkout,
            a.sha, a.base_sha, a.pr,
            host_observation_file=a.host_observation,
            trusted_controller=a.trusted_controller,
            trusted_policy=a.trusted_policy,
            controller_sha=a.controller_sha,
            expected_image_id=a.image_id,
            expected_policy_sha256=a.policy_sha256,
            include_validated_receipt=True,
        )
        if verification.get("independent_execution_provenance_verified") is not True:
            raise ValueError("Pinned host provenance verification is required")
        if a.key.is_symlink() or a.output.is_symlink():
            raise ValueError("Signing key and output cannot be symlinks")
        key_path = a.key.resolve(strict=True)
        candidate = a.checkout.resolve(strict=True)
        excluded = (candidate, a.trusted_controller.resolve(strict=True),
                    a.trusted_policy.resolve(strict=True), a.evidence_dir.resolve(strict=True))
        if any(key_path.is_relative_to(path) for path in excluded):
            raise ValueError("Signing key must remain outside repository, candidate and evidence")
        key_stat = key_path.stat()
        if (not key_path.is_file() or key_stat.st_nlink != 1
                or key_stat.st_uid != os.getuid()
                or stat.S_IMODE(key_stat.st_mode) != 0o600):
            raise ValueError("Signing key must be a host-owned 0600 regular file")
        verify_private_key(host_trust, key_path.read_bytes())
        if a.output.resolve().is_relative_to(candidate):
            raise ValueError("Signed output must remain outside candidate checkout")
        signed_bytes = canonical(sign(checked_receipt, key_path.read_bytes(), a.key_id, provenance)) + b"\n"
        descriptor = os.open(a.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(signed_bytes)
            output.flush()
            os.fsync(output.fileno())
        print("Attestation signed. Not a merge/deploy approval.")
    else:
        host_trust = load_host_trust(DEFAULT_TRUST_PATH)
        if (a.key.resolve(strict=True) != Path(host_trust["public_key_path"])
                or a.key_id != host_trust["key_id"]):
            raise ValueError("Verification key differs from host trust pins")
        verify_host_controller(host_trust, host_trust["controller_path"])
        verify_host_signer(host_trust, __file__)
        public = a.key.read_bytes()
        verify_host_key(host_trust, public)
        result = verify(json.loads(a.input.read_text(encoding="utf-8")), public, a.key_id)
        print(json.dumps({"sha": result["sha"], "status": result["status"]}))


if __name__ == "__main__":
    main()
