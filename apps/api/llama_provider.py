"""llama.cpp adapter. HTTP policy is translated at the API boundary."""
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
    choices: list[UpstreamChoice] = Field(min_length=1)
    model: str = Field(default="unknown", strict=True, min_length=1)
    usage: dict | None = None


async def generate_text(client: httpx.AsyncClient, base_url: str,
                        prompt: str, max_tokens: int) -> dict:
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
    started = time.perf_counter()
    try:
        response = await client.post(f"{base_url}/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = UpstreamResponse.model_validate(response.json())
    except httpx.TimeoutException:
        raise ProviderError(status_code=504, detail="Délai de réponse du serveur IA dépassé.") from None
    except httpx.HTTPError:
        raise ProviderError(status_code=502, detail="Erreur de communication avec le serveur IA.") from None
    except (ValueError, TypeError):
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

