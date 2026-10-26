"""Private, non-persistent Qwen check. No DB, secrets or prompts in output.

Without --generate, only tests GET /health. With --generate, performs two
real model calls using a synthetic Breton-fiction brief (no personal data).
"""
import argparse
import asyncio
import ipaddress
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from dotenv import load_dotenv

from apps.api.llama_provider import ProviderError, generate_text
from editorial.models import Brief
from editorial.service import SYSTEM_PROMPT, output_schema, parse_output, prompt_for


def private_model_url(value):
    if not isinstance(value, str):
        return None
    raw = value.strip().rstrip("/")
    try:
        url = urlsplit(raw)
        host = url.hostname or ""
        try:
            address = ipaddress.ip_address(host)
            allowed = address.is_private or address.is_loopback
        except ValueError:
            allowed = host.lower() in {"localhost", "host.docker.internal"}
        if (url.scheme not in {"http", "https"} or not allowed or not url.port
                or url.username or url.password or url.query or url.fragment
                or url.path not in {"", "/"}):
            return None
    except ValueError:
        return None
    return raw


async def verify(client, base_url, *, generate=False):
    """Safe aggregate report; use no real story/database/secret in the request."""
    report = {"health": "failed", "analysis": "not_run",
              "storyboard": "not_run", "calls": 0}
    if not private_model_url(base_url):
        report["health"] = "invalid_private_url"
        return report
    try:
        async with client.stream("GET", base_url.rstrip("/") + "/health",
                                 follow_redirects=False, timeout=3.0) as response:
            if response.status_code != 200:
                report["health"] = "unavailable"
                return report
    except (httpx.HTTPError, ValueError, TimeoutError):
        report["health"] = "unavailable"
        return report
    report["health"] = "ok"
    if not generate:
        return report

    brief = Brief(topic="Une légende bretonne entièrement fictive sur un phare",
                  genre="fiction", duration_seconds=60, scene_count=3)
    analysis = None
    for step in ("analysis", "storyboard"):
        try:
            response = await generate_text(
                client, base_url, prompt_for(step, brief, analysis), 2048,
                system_prompt=SYSTEM_PROMPT, json_schema=output_schema(step, brief))
            report["calls"] += 1
            if response["finish_reason"] != "stop":
                report[step] = "output_incomplete"
                return report
            parsed = parse_output(response["response"], step, brief)
        except ProviderError as exc:
            report[step] = {503: "configuration", 504: "timeout"}.get(
                exc.status_code, "provider_error")
            return report
        except (ValueError, TypeError, RecursionError):
            report[step] = "invalid_schema_output"
            return report
        report[step] = "ok"
        if step == "analysis":
            analysis = parsed
    return report


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true",
                        help="Two real, isolated model calls with synthetic prompts; no database writes")
    args = parser.parse_args(argv)
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    base_url = private_model_url(os.getenv("LLM_BASE_URL", ""))
    if base_url is None:
        print(json.dumps({"health": "invalid_private_url", "analysis": "not_run",
                          "storyboard": "not_run", "calls": 0}))
        return 2
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=5.0),
        trust_env=False, limits=httpx.Limits(max_connections=1)
    ) as client:
        report = await verify(client, base_url, generate=args.generate)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["health"] == "ok" and (
        not args.generate or (report["analysis"] == "ok" and report["storyboard"] == "ok")) else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
