"""Trusted Ed25519 evidence signing and verification; NEVER run with keys in candidate sandbox."""
import argparse
import base64
from datetime import datetime
import json
from pathlib import Path
import re
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

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


def sign(receipt, private_pem, key_id):
    validate(receipt)
    key = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", key_id):
        raise ValueError("Invalid signing configuration")
    return {"algorithm": "Ed25519", "key_id": key_id, "evidence": receipt,
            "signature": base64.b64encode(key.sign(canonical(receipt))).decode("ascii")}


def verify(envelope, public_pem, key_id):
    if not isinstance(envelope, dict) or set(envelope) != {"algorithm", "key_id", "evidence", "signature"} or envelope["algorithm"] != "Ed25519" or envelope["key_id"] != key_id:
        raise ValueError("Unexpected attestation")
    key = serialization.load_pem_public_key(public_pem)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("Not an Ed25519 public key")
    receipt = validate(envelope["evidence"])
    try:
        signature = base64.b64decode(envelope["signature"], validate=True)
        key.verify(signature, canonical(receipt))
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
    p.add_argument("--checkout", type=Path)
    p.add_argument("--sha")
    p.add_argument("--base-sha")
    p.add_argument("--pr", type=int)
    a = p.parse_args()
    if a.action == "sign":
        if not a.output or a.output.exists():
            p.error("Fresh --output required")
        if (not a.evidence_dir or not a.checkout or not a.sha
                or not a.base_sha or a.pr is None):
            p.error("Signing requires independent receipt/log and Git checkout checks")
        # Import at call time so validate() remains usable in offline unit tests.
        from scripts.arvor_ci_evidence_verify import verify_receipt
        verify_receipt(a.input, a.evidence_dir, a.checkout,
                       a.sha, a.base_sha, a.pr)
        signed = sign(json.loads(a.input.read_text(encoding="utf-8")), a.key.read_bytes(), a.key_id)
        a.output.write_bytes(canonical(signed) + b"\n")
        a.output.chmod(0o600)
        print("Attestation signed. Not a merge/deploy approval.")
    else:
        result = verify(json.loads(a.input.read_text(encoding="utf-8")), a.key.read_bytes(), a.key_id)
        print(json.dumps({"sha": result["sha"], "status": result["status"]}))


if __name__ == "__main__":
    main()
