import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from apps.api.llama_provider import ProviderError, generate_text, generation_gate
from editorial.api import create_router, get_identity, security
from apps.api.studio import router as studio_router
from fastapi.security import HTTPAuthorizationCredentials

# Existing process variables take precedence; never rewrite the environment file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

app = FastAPI(title="Directeur éditorial IA", version="0.1.0")


class GenerateRequest(BaseModel):
    prompt: str = Field(strict=True, min_length=1, max_length=16000)
    max_tokens: int = Field(default=250, strict=True, ge=1, le=2048)

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Le prompt ne doit pas être vide.")
        return value


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
    connection: Request,
    client: httpx.AsyncClient = Depends(get_llm_client),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
):
    # The unauthenticated legacy bootstrap is strictly loopback-only.
    # Checking both the client and Host prevents a proxied or rebound request
    # from being mistaken for a local browser.
    if any(os.getenv(name) for name in ("EDITORIAL_API_TOKEN", "EDITORIAL_TENANT_ID", "EDITORIAL_ACTOR_ID")):
        get_identity(credentials)
    elif (connection.client is None
          or connection.client.host not in {"127.0.0.1", "::1", "localhost"}
          or connection.url.hostname not in {"127.0.0.1", "::1", "localhost"}):
        raise HTTPException(403, "Amorçage anonyme réservé à la boucle locale.")
    if not generation_gate.acquire(blocking=False):
        raise HTTPException(429, "Génération déjà en cours : capacité temporairement atteinte.",
                            headers={"Retry-After": "30"})
    try:
        try:
            return await generate_text(
                client, os.getenv("LLM_BASE_URL", ""), request.prompt, request.max_tokens
            )
        except ProviderError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from None
    finally:
        generation_gate.release()


# Configured private identity; tenant and actor never come from request fields.
app.include_router(create_router(get_llm_client))
app.include_router(studio_router)

