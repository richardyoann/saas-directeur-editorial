import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

# Existing process variables take precedence; never rewrite the environment file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

app = FastAPI(title="Directeur éditorial IA", version="0.1.0")

from traceability.api import install as install_traceability

install_traceability(app)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    max_tokens: int = Field(default=250, ge=1, le=2048)

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Le prompt ne doit pas être vide.")
        return value


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


class UpstreamResponse(BaseModel):
    choices: list[UpstreamChoice] = Field(min_length=1)
    model: str = Field(default="unknown", strict=True, min_length=1)
    usage: dict | None = None


async def get_llm_client() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=5.0), trust_env=False
    ) as client:
        yield client


@app.get("/health")
def health():
    return {"status": "ok", "service": "editorial-api"}


@app.post("/ai/generate")
async def generate(
    request: GenerateRequest,
    client: httpx.AsyncClient = Depends(get_llm_client),
):
    base_url = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
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
        raise HTTPException(status_code=503, detail="LLM_BASE_URL absente ou invalide.")

    payload = {
        "messages": [{"role": "user", "content": request.prompt}],
        "max_tokens": request.max_tokens,
        "stream": False,
    }
    started = time.perf_counter()
    try:
        response = await client.post(f"{base_url}/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = UpstreamResponse.model_validate(response.json())
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai de réponse du serveur IA dépassé.") from None
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Erreur de communication avec le serveur IA.") from None
    except (ValueError, TypeError):
        raise HTTPException(status_code=502, detail="Réponse invalide du serveur IA.") from None

    return {
        "status": "success",
        "provider": "llama.cpp",
        "model": data.model,
        "prompt": request.prompt,
        "response": data.choices[0].message.content,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "usage": data.usage,
    }

