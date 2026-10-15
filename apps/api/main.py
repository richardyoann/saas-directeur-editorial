import asyncio
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from apps.api.llama_provider import ProviderError, generate_text, generation_gate
from editorial.api import create_router, get_identity
from apps.api.studio import router as studio_router
from editorial.worker_guard import worker_online
from apps.api.request_limits import RequestLimits
from uuid import UUID

# Existing process variables take precedence; never rewrite the environment file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)

@asynccontextmanager
async def lifespan(application: FastAPI):
    # One reusable provider client and one same-process API client per worker.
    async with (
        httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0),
                          limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
                          trust_env=False) as llm_client,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=application),
                          base_url="http://internal", timeout=275, trust_env=False) as internal_client,
    ):
        application.state.llm_client = llm_client
        application.state.internal_client = internal_client
        try:
            yield
        finally:
            del application.state.llm_client
            del application.state.internal_client


app = FastAPI(title="Directeur éditorial IA", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestLimits)


class GenerateRequest(BaseModel):
    prompt: str = Field(strict=True, min_length=1, max_length=16000)
    max_tokens: int = Field(default=250, strict=True, ge=1, le=2048)

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Le prompt ne doit pas être vide.")
        return value


async def get_llm_client(request: Request) -> AsyncIterator[httpx.AsyncClient]:
    shared = getattr(request.app.state, "llm_client", None)
    if shared is not None:
        yield shared
    else:
        # ASGITransport unit tests don't automatically start lifespan.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=5.0), trust_env=False
        ) as client:
            yield client


@app.get("/health")
def health():
    return {"status": "ok", "service": "editorial-api"}


def _database_ready():
    import psycopg
    url = os.getenv("PO_DATABASE_URL", "")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=2) as connection:
            return connection.execute("SELECT 1").fetchone() == (1,)
    except (psycopg.Error, OSError):
        return False


def _worker_ready():
    """Probe only the configured private tenant, no secrets in response."""
    url, tenant_id = os.getenv("PO_DATABASE_URL", ""), os.getenv("EDITORIAL_TENANT_ID", "")
    if not url:
        return False
    try:
        return worker_online(url, UUID(tenant_id))
    except (ValueError, OSError):
        return False
    except Exception:
        # A readiness check must never expose raw database errors.
        return False


@app.get("/ready")
async def ready(client: httpx.AsyncClient = Depends(get_llm_client)):
    """Readiness of DB and configured LLM, not proof of a running worker."""
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    database_ok = await asyncio.to_thread(_database_ready)
    model_ok = False
    if base.startswith(("http://", "https://")):
        try:
            response = await client.get(base + "/health", timeout=2.0)
            model_ok = response.status_code == 200
        except (httpx.HTTPError, ValueError):
            pass
    worker_ok = True
    if os.getenv("EDITORIAL_ASYNC_ENABLED", "").lower() == "true":
        worker_ok = database_ok and await asyncio.to_thread(_worker_ready)
    ok = database_ok and model_ok and worker_ok
    from fastapi.responses import JSONResponse
    return JSONResponse({"ready": ok}, status_code=200 if ok else 503)


@app.post("/ai/generate")
async def generate(
    request: GenerateRequest,
    client: httpx.AsyncClient = Depends(get_llm_client),
    _identity=Depends(get_identity),
):
    # Fail-closed everywhere, including loopback or requests forwarded by a proxy.
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

