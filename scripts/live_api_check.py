"""Real HTTP checks; never print model contents, endpoints or environment values."""
import json
import sys
from urllib.parse import urlsplit

import httpx


def check(base_url: str, client=None) -> dict:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Live tests require a loopback HTTP API")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Invalid local API URL")
    with (client or httpx.Client(timeout=150, trust_env=False)) as http:
        health = http.get(base_url.rstrip("/") + "/health")
        health.raise_for_status()
        if health.json().get("status") != "ok":
            raise ValueError("Health contract failed")
        invalid = http.post(base_url.rstrip("/") + "/ai/generate", json={"prompt": " "})
        if invalid.status_code != 422:
            raise ValueError("Input validation regression")
        response = http.post(base_url.rstrip("/") + "/ai/generate", json={
            "prompt": "Réponds uniquement avec le mot Bretagne.", "max_tokens": 32})
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "success" or data.get("provider") != "llama.cpp":
            raise ValueError("Generation contract failed")
        if not isinstance(data.get("response"), str) or not data["response"].strip():
            raise ValueError("Empty model result")
        if data.get("truncated") is True or data.get("finish_reason") not in {None, "stop"}:
            raise ValueError("Model did not complete normally")
        return {"health": "passed", "validation": "passed", "real_generation": "passed",
                "finish_reason_available": data.get("finish_reason") is not None}


if __name__ == "__main__":
    try:
        print(json.dumps(check(sys.argv[1]), sort_keys=True))
    except Exception:
        print('{"live_api": "failed"}', file=sys.stderr)
        raise SystemExit(1)
