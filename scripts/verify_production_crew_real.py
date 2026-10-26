"""Run real private Qwen against synthetic 75s crew contracts, WITHOUT any DB or media.

Output reports statuses only; never writes prompts, private credentials, or model
responses. One role by default; --all is explicit and stops at the first error.
"""
import argparse
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from apps.api.llama_provider import ProviderError
from editorial.models import Brief
from production.crew import ROLES, execute_role, quality_gate, source_snapshot


def private_url(value):
    if not isinstance(value, str) or not value:
        return None
    candidate = value.strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        if hostname in {"localhost", "host.docker.internal"}:
            allowed = True
        else:
            ip = ipaddress.ip_address(hostname or "")
            allowed = (ip.is_loopback or ip.is_private) and not any(
                (ip.is_unspecified, ip.is_multicast, ip.is_link_local, ip.is_reserved))
        if (not allowed or parsed.scheme not in {"http", "https"} or not parsed.port
                or parsed.username or parsed.password or parsed.path
                or parsed.query or parsed.fragment):
            return None
    except (ValueError, AttributeError, TypeError):
        return None
    return candidate


def synthetic_source():
    scene = {
        "title": "La lueur", "duration_seconds": 15,
        "narration": "Un phare mystérieux révèle une légende bretonne entièrement fictive.",
        "visual_description": "Un phare sur la côte dans la brume",
        "characters": ["Une gardienne"], "landscape": "Falaises bretonnes",
        "colors": ["vert", "gris"], "shot": "Plan large",
        "emotion": "Mystère", "sound": "Vagues",
        "image_prompt": "Phare breton fantastique",
    }
    brief = Brief(topic="Fiction-test : un phare enchanté",
                  genre="fiction", duration_seconds=75, scene_count=5)
    return source_snapshot({
        "type": "editorial_run", "status": "approved",
        "storyboard_stale": False, "review_revision": 1,
        "brief": brief.model_dump(),
        "storyboard": {
            "title": "La gardienne du phare",
            "synopsis": "Légende bretonne entièrement fictive pour un contrôle sans données privées.",
            "cast": [{"name": "Une gardienne",
                      "appearance": "Manteau bleu et cheveux bruns",
                      "personality": "Déterminée", "role": "Personnage principal"}],
            "scenes": [dict(scene) for _ in range(5)],
        },
    })


async def verify(client, base_url, *, all_roles=False):
    """No persistence, no automatic retry and no raw content in result."""
    result = {"mode": "all_seven" if all_roles else "first_role",
              "scope": "real_llm_text_only", "steps": [],
              "all_requested_steps_valid": False,
              "multimedia_checked": False, "human_approval": False}
    base_url = private_url(base_url)
    if not base_url:
        result["error"] = "private_llm_endpoint_missing_or_invalid"
        return result
    outputs = {}
    source = synthetic_source()
    selected = ROLES if all_roles else ROLES[:1]
    for role in selected:
        started = time.monotonic()
        try:
            output = await execute_role(client, base_url, role, source, outputs)
        except ProviderError as exc:
            result["steps"].append({"role": role, "status": "provider_error",
                                    "http_class": exc.status_code,
                                    "seconds": round(time.monotonic() - started, 2)})
            return result
        except (ValueError, TypeError, RecursionError):
            result["steps"].append({"role": role, "status": "invalid_structured_output",
                                    "seconds": round(time.monotonic() - started, 2)})
            return result
        outputs[role] = output
        result["steps"].append({"role": role, "status": "schema_valid",
                                "seconds": round(time.monotonic() - started, 2)})
    result["all_requested_steps_valid"] = True
    if "critic" in outputs:
        quality = quality_gate(outputs["critic"])
        result["critic_gate"] = {
            "score": quality["score"], "passed": quality["passed"],
            "blocking_count": quality["blocking_count"],
            "scope": quality["scope"],
        }
    return result


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true",
                        help="Explicitly ask Qwen to execute all seven roles once, sequentially")
    parser.add_argument("--url", default=None,
                        help="Private llama.cpp base URL (otherwise LLM_BASE_URL); do not include secrets")
    args = parser.parse_args(argv)
    base = args.url if args.url is not None else os.environ.get("LLM_BASE_URL", "")
    async with httpx.AsyncClient(timeout=httpx.Timeout(130.0, connect=5.0),
                                 trust_env=False,
                                 limits=httpx.Limits(max_connections=1)) as client:
        report = await verify(client, base, all_roles=args.all)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["all_requested_steps_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
