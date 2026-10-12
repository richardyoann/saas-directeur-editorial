import hmac
import os
from dataclasses import dataclass
from uuid import UUID
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from editorial.models import Brief, ReviewDecision
from editorial.service import run_workflow
from editorial.store import PostgresStore, RunConflict, RunMissing, ReviewInvalid

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


    @router.post("/runs/{run_id}/steps/{step}/review")
    async def review_step(run_id: UUID, step: Literal["analysis", "storyboard"], decision: ReviewDecision,
                          identity: Identity = Depends(get_identity), store: PostgresStore = Depends(get_store)):
        try:
            return await run_in_threadpool(store.review, identity.tenant, identity.actor, run_id, step, decision)
        except RunMissing:
            raise HTTPException(404, "Exécution introuvable.") from None
        except RunConflict:
            raise HTTPException(409, "Décision périmée ou résultat non révisable.") from None
        except ReviewInvalid:
            raise HTTPException(422, "Révision incompatible avec le résultat ou le brief.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible.") from None

    @router.get("/runs/{run_id}/reviews")
    async def review_history(run_id: UUID, limit: int = Query(default=20, ge=1, le=50),
                             before_revision: int | None = Query(default=None, ge=1, le=2147483647),
                             identity: Identity = Depends(get_identity), store: PostgresStore = Depends(get_store)):
        try:
            reviews = await run_in_threadpool(store.review_history, identity.tenant, run_id, limit, before_revision)
            return {"run_id": str(run_id), "reviews": reviews[:limit],
                    "next_before_revision": reviews[limit-1]["revision"] if len(reviews) > limit else None}
        except RunMissing:
            raise HTTPException(404, "Exécution introuvable.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible.") from None

    return router
