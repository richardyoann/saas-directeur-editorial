import hmac
import os
from dataclasses import dataclass
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from editorial.models import Brief
from editorial.service import run_workflow
from editorial.store import PostgresStore, RunConflict, RunMissing

security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Identity:
    tenant: UUID
    actor: UUID


def get_identity(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    token = os.getenv("EDITORIAL_API_TOKEN", "")
    try:
        identity = Identity(UUID(os.environ["EDITORIAL_TENANT_ID"]), UUID(os.environ["EDITORIAL_ACTOR_ID"]))
        if len(token) < 32:
            raise ValueError()
    except (KeyError, ValueError):
        raise HTTPException(503, "Authentification éditoriale non configurée.") from None
    if credentials is None or not hmac.compare_digest(credentials.credentials.encode(), token.encode()):
        raise HTTPException(401, "Authentification requise.", headers={"WWW-Authenticate": "Bearer"})
    return identity


def get_store():
    url = os.getenv("PO_DATABASE_URL", "")
    if not url:
        raise HTTPException(503, "Persistance éditoriale non configurée.")
    return PostgresStore(url)


def create_router(get_llm_client):
    router = APIRouter(prefix="/editorial", tags=["Editorial"])

    @router.post("/runs")
    async def create_run(brief: Brief, idempotency_key: UUID = Header(),
                         identity: Identity = Depends(get_identity),
                         store: PostgresStore = Depends(get_store), client=Depends(get_llm_client)):
        try:
            run, created = await run_workflow(store, identity.tenant, identity.actor,
                                             idempotency_key, brief, client, os.getenv("LLM_BASE_URL", ""))
        except RunConflict:
            raise HTTPException(409, "Clé d'idempotence déjà utilisée pour une autre demande.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible.") from None
        code = 201 if created else (202 if run["status"] == "running" else 200)
        if run["status"] == "failed":
            code = {"provider_configuration": 503, "provider_timeout": 504,
                    "provider_unavailable": 502}.get(run.get("error_code"), 422)
        return JSONResponse(run, status_code=code)

    @router.get("/runs/{run_id}")
    async def get_run(run_id: UUID, identity: Identity = Depends(get_identity),
                      store: PostgresStore = Depends(get_store)):
        try:
            return await run_in_threadpool(store.get, identity.tenant, run_id)
        except RunMissing:
            raise HTTPException(404, "Exécution introuvable.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible.") from None

    @router.get("/runs/{run_id}/history")
    async def get_history(run_id: UUID, identity: Identity = Depends(get_identity),
                          store: PostgresStore = Depends(get_store)):
        try:
            return {"run_id": str(run_id), "steps": await run_in_threadpool(store.history, identity.tenant, run_id)}
        except RunMissing:
            raise HTTPException(404, "Exécution introuvable.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible.") from None

    return router
