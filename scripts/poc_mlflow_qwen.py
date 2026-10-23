"""Isolated, opt-in MLflow probe for the existing local llama.cpp/Qwen adapter.

No production hook, database migration, media write, raw prompt, or raw response.
Run with --execute only after provisioning a PRIVATE MLflow test server.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import re
from urllib.parse import urlsplit

# Deliberately synthetic: the real story, prompts and answers are never exported.
SYNTHETIC_PROMPT = (
    "Écris deux phrases de fiction inspirées d'une légende bretonne. "
    "Ne présente aucun fait comme historiquement vérifié."
)
MAX_TOKENS = 160
EXPERIMENT = "arvor-qwen-local-poc"


def private_url(value: str, *, loopback_only: bool = False) -> str:
    """Allow direct loopback/private IPs only, never public telemetry endpoints."""
    value = value.strip()
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        if (parsed.scheme != "http" or not host or port is None
                or not 1 <= port <= 65535 or parsed.username or parsed.password
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ValueError()
        if host.lower() == "localhost":
            allowed = True
        else:
            address = ipaddress.ip_address(host)
            allowed = address.is_loopback or (
                not loopback_only and address.is_private
                and not address.is_link_local and not address.is_multicast
                and not address.is_unspecified and not address.is_reserved
            )
        if not allowed:
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError("URL non privée ou invalide.") from None
    return value.rstrip("/")


def token_metrics(usage: object) -> dict[str, int]:
    """Permit only bounded numeric counters, never arbitrary upstream content."""
    if not isinstance(usage, dict):
        return {}
    result = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(name)
        if type(value) is int and 0 <= value <= 10_000_000:
            result[name] = value
    return result


def safe_summary(result: dict) -> dict:
    """Reduce Qwen's response to non-content operational metadata."""
    model = result.get("model", "unknown")
    if not isinstance(model, str):
        model = "unknown"
    model = re.sub(r"[^a-zA-Z0-9_.:/-]", "_", model)[:100]
    duration = result.get("duration_seconds", 0)
    if type(duration) not in (float, int) or not 0 <= duration < 100_000:
        duration = 0
    finish = result.get("finish_reason", "unknown")
    if finish not in ("stop", "length"):
        finish = "other"
    response = result.get("response", "")
    return {
        "status": "ok",
        "model": model,
        "duration_seconds": float(duration),
        "response_characters": len(response) if isinstance(response, str) else 0,
        "finish_reason": finish,
        "tokens": token_metrics(result.get("usage")),
    }


async def execute_probe(mlflow, *, tracking_uri: str, model_url: str) -> dict:
    """Call the real, existing adapter once; log only sanitized metadata."""
    import httpx
    from apps.api.llama_provider import ProviderError, generate_text
    from mlflow.entities import SpanType

    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(EXPERIMENT)
    digest = hashlib.sha256(SYNTHETIC_PROMPT.encode("utf-8")).hexdigest()
    with mlflow.start_run(run_name="synthetic-qwen-smoke") as run:
        mlflow.log_param("prompt_sha256", digest)
        mlflow.log_param("prompt_source", "synthetic")
        mlflow.log_param("max_tokens", MAX_TOKENS)
        with mlflow.start_span(name="llama.cpp-qwen", span_type=SpanType.LLM) as span:
            span.set_inputs({"prompt_sha256": digest, "max_tokens": MAX_TOKENS})
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(120.0, connect=5.0), trust_env=False
                ) as client:
                    raw = await generate_text(
                        client, model_url, SYNTHETIC_PROMPT, MAX_TOKENS
                    )
                summary = safe_summary(raw)
            except ProviderError as error:
                # Never include error.detail: its value is not a telemetry contract.
                summary = {"status": "error", "error_code": f"provider_{error.status_code}"}
            span.set_outputs(summary)
            span.set_attribute("status", summary["status"])
            if summary["status"] == "ok":
                span.set_attribute("model", summary["model"])
                mlflow.log_param("model", summary["model"])
                mlflow.log_param("finish_reason", summary["finish_reason"])
                mlflow.log_metric("duration_seconds", summary["duration_seconds"])
                mlflow.log_metric("response_characters", summary["response_characters"])
                for metric, value in summary["tokens"].items():
                    mlflow.log_metric(metric, value)
            else:
                mlflow.set_tag("error_code", summary["error_code"])
        mlflow.set_tag("result", summary["status"])
        return {"mlflow_run_id": run.info.run_id, **summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arvor Qwen / MLflow private PoC")
    parser.add_argument(
        "--execute", action="store_true",
        help="Call Qwen exactly once and write private, redacted MLflow telemetry.",
    )
    args = parser.parse_args(argv)
    tracking = os.getenv("ARVOR_MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
    model = os.getenv("LLM_BASE_URL", "")
    try:
        tracking = private_url(tracking, loopback_only=True)
        model = private_url(model)
    except ValueError:
        print(json.dumps({"status": "invalid_private_configuration"}))
        return 2
    if not args.execute:
        print(json.dumps({"status": "configured", "generation": "not_started"}))
        return 0
    try:
        import mlflow
    except ImportError:
        print(json.dumps({"status": "mlflow_not_installed"}))
        return 2
    try:
        summary = asyncio.run(execute_probe(mlflow, tracking_uri=tracking, model_url=model))
    except Exception:
        # Deliberately omit stack traces: libraries may include URLs or secrets.
        print(json.dumps({"status": "probe_error", "details": "see_private_diagnostics"}))
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
