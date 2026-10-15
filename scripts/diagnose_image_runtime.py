"""Read-only SD.cpp image-service preflight.

No prompt submission, generation, model download, file mutation, or secrets.
HTTP requests are restricted to the configured private IMAGE_BASE_URL.
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Direct execution sets sys.path[0] to scripts/, not the repository root.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from editorial.visuals import private_image_url


def inspect_models(client, base_url):
    if not private_image_url(base_url):
        return {"ready": False, "reason": "invalid_or_public_image_url"}
    try:
        response = client.get(base_url.rstrip("/") + "/v1/models",
                              timeout=5.0, follow_redirects=False)
        if response.status_code != 200 or len(response.content) > 65536:
            return {"ready": False, "reason": "model_endpoint_unavailable"}
        payload = response.json()
        models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(models, list) or not models:
            return {"ready": False, "reason": "model_list_missing"}
        available = any(
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and 1 <= len(item["id"]) <= 150
            for item in models
        )
        if not available:
            return {"ready": False, "reason": "model_list_invalid"}
        return {"ready": True, "reason": "image_api_models_listed",
                "model_count": len(models)}
    except (httpx.HTTPError, ValueError, TypeError):
        return {"ready": False, "reason": "model_endpoint_unavailable"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("IMAGE_BASE_URL", ""))
    args = parser.parse_args(argv)
    try:
        with httpx.Client(trust_env=False, timeout=5) as client:
            data = inspect_models(client, args.url)
    except (OSError, ValueError):
        data = {"ready": False, "reason": "diagnostic_error"}
    # Note: a models list is not proof of Vulkan, GPU execution or valid images.
    data["gpu_verified"] = False
    data["generation_verified"] = False
    data["model_identity_verified"] = False
    data["vram_peak_bytes"] = None
    print(json.dumps(data, sort_keys=True))
    return 0 if data["ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
