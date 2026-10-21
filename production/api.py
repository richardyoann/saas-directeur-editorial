"""Private, authenticated, explicit-step production agents API."""
import os
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from apps.api.llama_provider import ProviderError, generation_gate
from editorial.api import get_identity, get_store, Identity
from editorial.store import PostgresStore, RunConflict, RunMissing
from production.crew import ROLES, SPECIALISTS, execute_role
from production.store import ProductionStore


class Advance(BaseModel):
    expected_revision: int = Field(strict=True, ge=0)


class Correction(Advance):
    target_role: str


def create_production_router(get_llm_client):
    router = APIRouter(prefix="/editorial/runs", tags=["Production"])

    @router.get("/{run_id}/production")
    async def get_production(run_id: UUID, identity: Identity = Depends(get_identity),
                             store: PostgresStore = Depends(get_store)):
        try:
            return await run_in_threadpool(ProductionStore(store).get, identity.tenant, run_id)
        except RunMissing:
            raise HTTPException(404, "Dossier de production introuvable.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance indisponible.") from None

    @router.post("/{run_id}/production")
    async def create_production(run_id: UUID, identity: Identity = Depends(get_identity),
                                store: PostgresStore = Depends(get_store)):
        try:
            state, created = await run_in_threadpool(ProductionStore(store).start, identity.tenant,
                                                      identity.actor, run_id)
            from fastapi.responses import JSONResponse
            return JSONResponse(state, status_code=201 if created else 200)
        except RunMissing:
            raise HTTPException(404, "Histoire introuvable.") from None
        except (ValueError, RunConflict):
            raise HTTPException(409, "Un storyboard approuvé de 75 secondes est requis.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance indisponible.") from None

    @router.post("/{run_id}/production/advance")
    async def advance_production(run_id: UUID, command: Advance,
                                 identity: Identity = Depends(get_identity),
                                 store: PostgresStore = Depends(get_store),
                                 client=Depends(get_llm_client)):
        if not generation_gate.acquire(blocking=False):
            raise HTTPException(429, "Capacité de génération temporairement atteinte.",
                                headers={"Retry-After": "30"})
        production = ProductionStore(store)
        try:
            try:
                state = await run_in_threadpool(production.claim, identity.tenant, identity.actor,
                                                run_id, command.expected_revision)
            except RunMissing:
                raise HTTPException(404, "Dossier de production introuvable.") from None
            except (RunConflict, ValueError):
                raise HTTPException(409, "Étape déjà prise ou storyboard modifié.") from None
            role = state["current_role"]
            error, result = None, None
            try:
                result = await execute_role(client, os.getenv("LLM_BASE_URL", ""), role,
                                            state["source"], state["outputs"], state["feedback"])
            except ProviderError as exc:
                error = {503: "provider_configuration", 504: "provider_timeout"}.get(
                    exc.status_code, "provider_unavailable")
            except (ValueError, TypeError):
                error = "invalid_structured_output"
            try:
                final = await run_in_threadpool(production.finish, identity.tenant, identity.actor,
                                                run_id, state["revision"], role, result, error)
            except (RunConflict, ValueError):
                raise HTTPException(409, "Résultat incertain : diagnostic manuel requis.") from None
            if error:
                # Never replay: the failure and current stage remain durably recorded.
                return __error_response(final, error)
            return final
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible. Vérifiez le run avant toute action.") from None
        finally:
            generation_gate.release()

    @router.post("/{run_id}/production/revise")
    async def revise_production(run_id: UUID, command: Correction,
                                identity: Identity = Depends(get_identity),
                                store: PostgresStore = Depends(get_store)):
        if command.target_role not in SPECIALISTS:
            raise HTTPException(422, "Métier de correction invalide.")
        try:
            return await run_in_threadpool(ProductionStore(store).request_correction,
                                           identity.tenant, identity.actor, run_id,
                                           command.expected_revision, command.target_role)
        except RunMissing:
            raise HTTPException(404, "Dossier introuvable.") from None
        except (RunConflict, ValueError):
            raise HTTPException(409, "Correction non autorisée ou version périmée.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance indisponible.") from None

    @router.post("/{run_id}/production/reconcile")
    async def reconcile_production(run_id: UUID, command: Advance,
                                   identity: Identity = Depends(get_identity),
                                   store: PostgresStore = Depends(get_store)):
        try:
            return await run_in_threadpool(ProductionStore(store).reconcile,
                                           identity.tenant, identity.actor, run_id,
                                           command.expected_revision)
        except RunMissing:
            raise HTTPException(404, "Dossier introuvable.") from None
        except (RunConflict, ValueError):
            raise HTTPException(409, "Réconciliation non autorisée : étape encore active ou version périmée.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance indisponible.") from None

    @router.get("/{run_id}/production/history")
    async def production_history(run_id: UUID, identity: Identity = Depends(get_identity),
                                 store: PostgresStore = Depends(get_store)):
        try:
            return await run_in_threadpool(ProductionStore(store).history, identity.tenant, run_id)
        except RunMissing:
            raise HTTPException(404, "Dossier introuvable.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance indisponible.") from None

    return router


def __error_response(final, code):
    from fastapi.responses import JSONResponse
    return JSONResponse(final, status_code=504 if code == "provider_timeout" else
                        503 if code == "provider_configuration" else 422
                        if code == "invalid_structured_output" else 502)
