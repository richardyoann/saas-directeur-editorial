"""Read-only, fail-closed attestation of the release actually running on the PC.

Does not approve a SHA, deploy code, change systemd or touch business data.
"""
import argparse
import http.client
import json
from pathlib import Path
import re
import subprocess

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_RECEIPT_OK = {
    "regression": "passed",
    "candidate_live": "passed",
    "installed_live": "passed",
    "real_editorial_workflow": "passed",
    "database_migration": "test_database_only",
    "production_editorial_probe": "read_only",
}


def read_service():
    output = subprocess.check_output(
        ["systemctl", "--user", "show", "editorial-api.service",
         "--property=MainPID,ActiveState,WorkingDirectory", "--no-pager"],
        text=True, timeout=5, stderr=subprocess.DEVNULL)
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def probe_loopback(path, port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        status = response.status
        if path == '/studio':
            # Only availability is checked here; the HTML exceeds the JSON cap.
            return status, None
        body = response.read(8193)
        if len(body) > 8192:
            raise ValueError("http_response_too_large")
        if path in {"/health", "/ready"}:
            try:
                return status, json.loads(body)
            except (ValueError, UnicodeDecodeError):
                raise ValueError("invalid_health_response") from None
        return status, None
    finally:
        connection.close()


def verify(root, sha, *, proc_root=Path("/proc"), service_reader=read_service,
           probe=probe_loopback, port=8000):
    """Return bounded, non-sensitive evidence; raise on absent or mismatched proof."""
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise ValueError("invalid_expected_sha")
    if not 1024 <= port <= 65535:
        raise ValueError("invalid_port")
    root = Path(root).resolve(strict=True)
    releases = (root / "releases").resolve(strict=True)
    current = root / "current"
    if not current.is_symlink():
        raise ValueError("active_release_symlink_missing")
    target = current.resolve(strict=True)
    if (not target.is_dir() or target.parent != releases or
            not re.fullmatch(re.escape(sha) + r"-[0-9]+", target.name)):
        raise ValueError("active_release_sha_mismatch")
    receipt_path = root / "last_delivery.json"
    if not receipt_path.is_file() or receipt_path.is_symlink():
        raise ValueError("delivery_receipt_missing_or_unsafe")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        raise ValueError("delivery_receipt_invalid") from None
    if (not isinstance(receipt, dict) or receipt.get("sha") != sha or
            any(receipt.get(key) != value for key, value in _RECEIPT_OK.items())):
        raise ValueError("delivery_receipt_does_not_prove_success")
    service = service_reader()
    if (service.get("ActiveState") != "active" or
            service.get("WorkingDirectory") != str(current) or
            not str(service.get("MainPID", "")).isdecimal() or
            int(service["MainPID"]) <= 0):
        raise ValueError("api_service_identity_invalid")
    try:
        process_cwd = (Path(proc_root) / service["MainPID"] / "cwd").resolve(strict=True)
    except OSError:
        raise ValueError("api_process_identity_unavailable") from None
    if process_cwd != target:
        raise ValueError("api_process_not_running_expected_release")
    for path in ("/health", "/ready", "/studio"):
        status, data = probe(path, port)
        if (status != 200 or
                (path == "/health" and (not isinstance(data, dict) or data.get("status") != "ok")) or
                (path == "/ready" and (not isinstance(data, dict) or data.get("ready") is not True))):
            raise ValueError("http_release_probe_failed")
    return {"verified": True, "sha": sha, "active_release": "matched",
            "receipt": "passed", "service_process": "matched",
            "health": "passed", "ready": "passed", "studio": "passed",
            "business_data_mutation": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        result = verify(args.root, args.expected_sha, port=args.port)
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
            http.client.HTTPException, TimeoutError, ConnectionError):
        print(json.dumps({"verified": False, "sha": args.expected_sha if _SHA.fullmatch(args.expected_sha) else None,
                          "reason": "release_evidence_missing_or_inconsistent"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
