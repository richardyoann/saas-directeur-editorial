"""Read-only diagnosis: no generation, retry, database migration or raw contents."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from editorial.models import Brief
from editorial.service import parse_output
from scripts.live_api_check import SAFE_ERRORS


def diagnose(base_url, run_id, token, client=None):
    parsed = urlsplit(base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("loopback_api_required")
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("authentication_not_configured")
    run_id = str(UUID(str(run_id)))
    endpoint = base_url.rstrip("/") + "/editorial/runs/" + run_id
    headers = {"Authorization": "Bearer " + token}
    with (client or httpx.Client(timeout=15, trust_env=False, follow_redirects=False)) as http:
        current = http.get(endpoint, headers=headers)
        current.raise_for_status()
        history = http.get(endpoint + "/history", headers=headers)
        history.raise_for_status()
        run, snapshots = current.json(), history.json()["steps"]
    brief = Brief.model_validate(run["brief"])
    report = {"status": run["status"] if run["status"] in {"running", "failed", "waiting_validation"} else "unknown",
              "error_code": run.get("error_code") if run.get("error_code") in SAFE_ERRORS else None,
              "steps": []}
    for index, snapshot in enumerate(snapshots[:2]):
        step = "analysis" if index == 0 else "storyboard"
        reason = snapshot.get("response_metadata", {}).get("finish_reason")
        try:
            parse_output(snapshot.get("raw_response"), step, brief)
            valid = True
        except (ValueError, TypeError):
            valid = False
        report["steps"].append({"step": step, "finish_reason": reason if reason in {"stop", "length", "content_filter"} else "unknown",
                                "schema_valid": valid,
                                "error_code": snapshot.get("error_code") if snapshot.get("error_code") in SAFE_ERRORS else None})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True, type=UUID)
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    try:
        report = diagnose(os.getenv("EDITORIAL_LOCAL_API_URL", "http://127.0.0.1:8000"),
                          args.run_id, os.getenv("EDITORIAL_API_TOKEN", ""))
        print(json.dumps(report, sort_keys=True))
    except Exception:
        print('{"diagnostic":"unavailable"}', file=sys.stderr)
        raise SystemExit(1) from None
