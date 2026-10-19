import asyncio
import os
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from apps.api.llama_provider import ProviderError, generate_text, generation_gate
from editorial.api import create_router, get_identity
from apps.api.studio import router as studio_router
from editorial.worker_guard import worker_online
from editorial.runtime_secrets import secret
from apps.api.request_limits import RequestLimits
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


# Keep the private API contract out of public documentation by default.
# Enable explicitly only in a trusted development environment.
_ENABLE_DOCS = os.getenv("EDITORIAL_ENABLE_API_DOCS", "false").lower() == "true"
app = FastAPI(
    title="Directeur éditorial IA", version="0.1.0", lifespan=lifespan,
    docs_url="/docs" if _ENABLE_DOCS else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _ENABLE_DOCS else None,
)
_READY_TTL_SECONDS = 2.0
_ready_lock = asyncio.Lock()
_ready_cache = {"until": 0.0, "key": None, "ok": False}

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
    url = secret("PO_DATABASE_URL")
    if not url:
        return False
    try:
        with psycopg.connect(url, connect_timeout=2) as connection:
            # Read-only readiness must validate the application schema,
            # not merely a reachable database port.
            row = connection.execute(
                "SELECT to_regclass('po_entity') IS NOT NULL, "
                "to_regclass('po_audit') IS NOT NULL, "
                "to_regclass('po_outbox') IS NOT NULL, "
                "to_regclass('po_batch') IS NOT NULL"
            ).fetchone()
            return bool(row and all(row))
    except (psycopg.Error, OSError):
        return False


def _worker_ready():
    """Probe only the configured private tenant, no secrets in response."""
    url, tenant_id = secret("PO_DATABASE_URL"), secret("EDITORIAL_TENANT_ID")
    if not url:
        return False
    try:
        return worker_online(url, UUID(tenant_id))
    except (ValueError, OSError):
        return False
    except Exception:
        # A readiness check must never expose raw database errors.
        return False


@app.get("/ready", include_in_schema=False)
async def ready(client: httpx.AsyncClient = Depends(get_llm_client)):
    """Cached private readiness: avoid opening DB + probing LLM per request.

    This cache is process-local; deploy behind the trusted local reverse proxy
    or restrict the route to loopback. It never exposes dependency details.
    """
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    async_mode = os.getenv("EDITORIAL_ASYNC_ENABLED", "").lower() == "true"
    key = (secret("PO_DATABASE_URL"), base, async_mode,
           secret("EDITORIAL_TENANT_ID"))
    async with _ready_lock:
        current = time.monotonic()
        if _ready_cache["key"] != key or current >= _ready_cache["until"]:
            database_ok = await asyncio.to_thread(_database_ready)
            model_ok = False
            if base.startswith(("http://", "https://")):
                try:
                    response = await client.get(base + "/health", timeout=2.0)
                    model_ok = response.status_code == 200
                except (httpx.HTTPError, ValueError):
                    pass
            worker_ok = not async_mode
            if async_mode:
                worker_ok = database_ok and await asyncio.to_thread(_worker_ready)
            _ready_cache.update(
                ok=bool(database_ok and model_ok and worker_ok),
                key=key,
                until=time.monotonic() + _READY_TTL_SECONDS,
            )
        ok = _ready_cache["ok"]
    from fastapi.responses import JSONResponse
    return JSONResponse(
        {"ready": ok}, status_code=200 if ok else 503,
        headers={"Cache-Control": "no-store"},
    )

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

