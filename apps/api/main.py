import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from apps.api.llama_provider import ProviderError, generate_text

# Existing process variables take precedence; never rewrite the environment file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

app = FastAPI(title="Directeur éditorial IA", version="0.1.0")


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    max_tokens: int = Field(default=250, ge=1, le=2048)

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
    client: httpx.AsyncClient = Depends(get_llm_client),
):
    try:
        return await generate_text(
            client, os.getenv("LLM_BASE_URL", ""), request.prompt, request.max_tokens
        )
    except ProviderError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from None
