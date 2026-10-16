"""Read-only integrity/audit check. Never generates images or accepts artistry."""
import argparse
import json
import os
from pathlib import Path
import sys
from uuid import UUID

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from editorial.visuals import private_image_url


def inspect_receipts(client, base_url, token, run_id, expected_scenes):
    failure = {"technical_passed": False, "gpu_verified": False,
               "human_visual_review_required": True, "reason": "verification_unavailable"}
    if not private_image_url(base_url) or len(token) < 32:
        return failure
    try:
        response = client.get(
            base_url.rstrip("/") + f"/editorial/runs/{run_id}/visuals/verification",
            params={"expected_scenes": expected_scenes},
            headers={"Authorization": "Bearer " + token}, timeout=10,
            follow_redirects=False,
        )
        if response.status_code != 200 or len(response.content) > 65536:
            return failure
        report = response.json()
        if (not isinstance(report, dict) or report.get("run_id") != str(run_id)
                or type(report.get("technical_passed")) is not bool
                or not isinstance(report.get("scenes"), list)
                or report.get("expected_scenes") != expected_scenes):
            return failure
        if report["technical_passed"] and (
                len(report["scenes"]) != expected_scenes
                or any(not isinstance(scene, dict) or scene.get("passed") is not True
                       for scene in report["scenes"])):
            return failure
        # This client deliberately cannot turn an endpoint result into GPU proof.
        report.update(gpu_verified=False, human_visual_review_required=True)
        return report
    except (httpx.HTTPError, ValueError, TypeError):
        return failure


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=UUID, required=True)
    parser.add_argument("--expected-scenes", type=int, choices=range(1, 7), default=3)
    parser.add_argument("--url", default=os.getenv("EDITORIAL_API_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args(argv)
    with httpx.Client(trust_env=False) as client:
        report = inspect_receipts(client, args.url, os.getenv("EDITORIAL_API_TOKEN", ""),
                                  args.run_id, args.expected_scenes)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["technical_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
