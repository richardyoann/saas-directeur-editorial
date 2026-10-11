"""llama.cpp adapter. HTTP policy is translated at the API boundary."""
import asyncio
import json
import time
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, field_validator


class ProviderError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class UpstreamMessage(BaseModel):
    content: str = Field(strict=True, min_length=1)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Contenu amont vide.")
        return value


class UpstreamChoice(BaseModel):
    message: UpstreamMessage
    finish_reason: str | None = Field(default=None, strict=True)


class UpstreamResponse(BaseModel):
    choices: list[UpstreamChoice] = Field(min_length=1, max_length=1)
    model: str = Field(default="unknown", strict=True, min_length=1)
    usage: dict | None = None


def strict_json(body):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError("non_finite_json")
    return json.loads(body, object_pairs_hook=pairs, parse_constant=reject_constant)


def validate_request(prompt, max_tokens, system_prompt, json_schema):
    if (not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > 65536
            or type(max_tokens) is not int or not 1 <= max_tokens <= 2048):
        raise ProviderError(422, "Requête IA hors limites.")
    if system_prompt is not None and (not isinstance(system_prompt, str)
            or not system_prompt.strip() or len(system_prompt.encode("utf-8")) > 8192):
        raise ProviderError(422, "Consignes IA invalides.")
    if json_schema is not None:
        if not isinstance(json_schema, dict):
            raise ProviderError(422, "Schéma IA invalide.")
        try:
            encoded = json.dumps(json_schema, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, RecursionError):
            raise ProviderError(422, "Schéma IA invalide.") from None
        if len(encoded) > 32768:
            raise ProviderError(422, "Schéma IA trop volumineux.")


async def generate_text(client: httpx.AsyncClient, base_url: str,
                        prompt: str, max_tokens: int, *, system_prompt: str | None = None,
                        json_schema: dict | None = None) -> dict:
    validate_request(prompt, max_tokens, system_prompt, json_schema)
    base_url = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(base_url)
        valid_url = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.port != 0
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid_url = False
    if not valid_url:
        raise ProviderError(status_code=503, detail="LLM_BASE_URL absente ou invalide.")

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": False,
    }
    if system_prompt is not None:
        payload["messages"].insert(0, {"role": "system", "content": system_prompt})
    if json_schema is not None:
        # llama.cpp's documented schema form; never fall back to unconstrained text.
        payload["response_format"] = {"type": "json_object", "schema": json_schema}
        payload["temperature"] = 0.1
    started = time.perf_counter()
    try:
        # Bound wall time AND decoded response bytes, including chunked bodies.
        async with asyncio.timeout(120):
            async with client.stream("POST", f"{base_url}/v1/chat/completions",
                                     json=payload, follow_redirects=False) as response:
                response.raise_for_status()
                if response.is_redirect:
                    raise ProviderError(502, "Redirection du serveur IA refusée.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 262144:
                        raise ProviderError(502, "Réponse du serveur IA trop volumineuse.")
                    body.extend(chunk)
                data = UpstreamResponse.model_validate(strict_json(body))
    except (httpx.TimeoutException, TimeoutError):
        raise ProviderError(status_code=504, detail="Délai de réponse du serveur IA dépassé.") from None
    except httpx.HTTPError:
        raise ProviderError(status_code=502, detail="Erreur de communication avec le serveur IA.") from None
    except (ValueError, TypeError, RecursionError):
        raise ProviderError(status_code=502, detail="Réponse invalide du serveur IA.") from None

    return {
        "status": "success",
        "provider": "llama.cpp",
        "model": data.model,
        "prompt": prompt,
        "response": data.choices[0].message.content,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "usage": data.usage,
        "finish_reason": data.choices[0].finish_reason,
        "truncated": data.choices[0].finish_reason == "length",
    }


