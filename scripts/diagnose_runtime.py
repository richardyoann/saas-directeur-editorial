"""Read-only private PC release diagnostic. No deployment or secret output.

Usage: python scripts/diagnose_runtime.py --root /path/to/editorial-runtime
Only sends GET requests to loopback and reads systemd/release metadata.
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

import httpx
from dotenv import dotenv_values


def service_info(name):
    try:
        output = subprocess.check_output(
            ["systemctl", "--user", "show", name,
             "--property=ActiveState,SubState,MainPID,WorkingDirectory",
             "--no-pager"], text=True, stderr=subprocess.DEVNULL, timeout=3)
        result = {}
        for line in output.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                if key in {"ActiveState", "SubState", "MainPID"}:
                    result[key] = value
        return result
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {"ActiveState": "unknown"}


def release_info(root, expected):
    current = root / "current"
    receipt = root / "last_delivery.json"
    result = {"root_present": root.is_dir(), "symlink_present": current.is_symlink(),
              "receipt_present": receipt.is_file(), "current_sha": None,
              "receipt_sha": None, "expected_sha_matches": None}
    if current.is_symlink():
        try:
            target = current.resolve(strict=True)
            match = re.fullmatch(r"([0-9a-f]{40})-[0-9]+", target.name)
            result["current_sha"] = match.group(1) if match else None
        except OSError:
            pass
    if receipt.is_file():
        try:
            data = json.loads(receipt.read_text())
            value = data.get("sha")
            if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value):
                result["receipt_sha"] = value
        except (OSError, ValueError):
            pass
    if expected:
        result["expected_sha_matches"] = (result["current_sha"] == expected and
                                            result["receipt_sha"] == expected)
    result["release_receipt_consistent"] = bool(result["current_sha"] and
                                                    result["current_sha"] == result["receipt_sha"])
    return result


def config_info(root):
    """Only presence/flag values, never reveal credentials or paths."""
    link = root / "current" / ".env"
    if not link.is_file():
        return {"config_found": False}
    try:
        values = dotenv_values(link)
    except (OSError, UnicodeError, ValueError):
        return {"config_found": False}
    mandatory = ("PO_DATABASE_URL", "EDITORIAL_API_TOKEN",
                 "EDITORIAL_WEB_PASSWORD", "EDITORIAL_TENANT_ID",
                 "EDITORIAL_ACTOR_ID", "LLM_BASE_URL")
    return {"config_found": True, "configured": {
        key: bool(values.get(key)) for key in mandatory},
        "async_enabled": str(values.get("EDITORIAL_ASYNC_ENABLED", "false")).lower() == "true"}


def http_info(port):
    results = {}
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=3, trust_env=False) as client:
        for path in ("/health", "/ready", "/studio", "/studio/session"):
            try:
                response = client.get(path)
                results[path] = response.status_code
            except httpx.HTTPError:
                results[path] = None
    return results


def diagnose(root, port, expected=None):
    return {
        "release": release_info(root, expected),
        "api_service": service_info("editorial-api.service"),
        "worker_service": service_info("editorial-worker.service"),
        "configuration": config_info(root),
        "http_status": http_info(port),
        "notes": [
            "Lecture seule : aucune migration, activation, connexion ou génération.",
            "Le statut /ready=503 peut signaler PostgreSQL, Qwen ou un worker absent.",
            "Une CI GitHub verte n'atteste pas de la release active sur ce PC.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.home() / "editorial-runtime")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--expected-sha", default=None)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Invalid local API port")
    if args.expected_sha and not re.fullmatch(r"[0-9a-f]{40}", args.expected_sha):
        parser.error("Expected SHA must contain 40 hexadecimal characters")
    print(json.dumps(diagnose(args.root.expanduser(), args.port, args.expected_sha),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
