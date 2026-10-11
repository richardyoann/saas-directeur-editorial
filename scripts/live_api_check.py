"""Real HTTP checks; never print model contents, endpoints or environment values."""
import json
import sys
from urllib.parse import urlsplit
from uuid import UUID

import httpx


def check(base_url: str, client=None, editorial_token=None, idempotency_key=None) -> dict:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Live tests require a loopback HTTP API")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Invalid local API URL")
    if (editorial_token is None) != (idempotency_key is None):
        raise ValueError("Editorial credentials and key must be supplied together")
    result = {"health": "passed", "validation": "passed",
              "real_generation": "passed", "finish_reason_available": True}
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
        if data.get("truncated") is True or data.get("finish_reason") != "stop":
            raise ValueError("Model did not complete normally")
        if editorial_token is not None:
            if not isinstance(editorial_token, str) or len(editorial_token) < 32:
                raise ValueError("Editorial authentication is not configured")
            key = str(UUID(str(idempotency_key)))
            brief = {"topic": "Contrôle technique privé de la chaîne éditoriale",
                     "genre": "legend", "duration_seconds": 15, "scene_count": 1,
                     "audience": "Test technique", "tone": "Factuel", "sources": []}
            endpoint = base_url.rstrip("/") + "/editorial/runs"
            unauthenticated = http.post(endpoint, headers={"Idempotency-Key": key}, json=brief)
            if unauthenticated.status_code != 401:
                raise ValueError("Editorial authentication regression")
            headers = {"Authorization": "Bearer " + editorial_token,
                       "Idempotency-Key": key}
            created = http.post(endpoint, headers=headers, json=brief)
            if created.status_code not in {200, 201}:
                raise ValueError("Editorial workflow request failed")
            run = created.json()
            if (run.get("status") != "waiting_validation"
                    or run.get("requires_human_validation") is not True
                    or len(run.get("steps", [])) != 2):
                raise ValueError("Editorial workflow contract failed")
            run_id = str(UUID(run["id"]))
            replay = http.post(endpoint, headers=headers, json=brief)
            if replay.status_code != 200 or replay.json().get("id") != run_id:
                raise ValueError("Editorial idempotency failed")
            current = http.get(endpoint + "/" + run_id,
                               headers={"Authorization": "Bearer " + editorial_token})
            current.raise_for_status()
            if current.json().get("status") != "waiting_validation":
                raise ValueError("Editorial persistence failed")
            history = http.get(endpoint + "/" + run_id + "/history",
                               headers={"Authorization": "Bearer " + editorial_token})
            history.raise_for_status()
            steps = history.json().get("steps")
            if (not isinstance(steps, list) or len(steps) != 2
                    or any(step.get("error_code") is not None
                           or step.get("response_metadata", {}).get("finish_reason") != "stop"
                           for step in steps)):
                raise ValueError("Editorial history or completion evidence failed")
            result.update(real_editorial_workflow="passed",
                          persistence="passed", idempotency="passed")
        return result


if __name__ == "__main__":
    try:
        print(json.dumps(check(sys.argv[1]), sort_keys=True))
    except Exception:
        print('{"live_api": "failed"}', file=sys.stderr)
        raise SystemExit(1)
