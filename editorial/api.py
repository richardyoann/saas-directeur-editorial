import hmac
import hashlib
import os
import time
from dataclasses import dataclass
from uuid import UUID
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from apps.api.llama_provider import generation_gate
from editorial.models import Brief, ReviewDecision
from editorial.service import run_workflow
from editorial.store import PostgresStore, RunConflict, RunMissing, ReviewInvalid
from editorial.worker_guard import WorkerOffline
from editorial.visuals import ImageUnavailable, image_gate, media_preflight, load_png, render_png, save_png, validate_png, private_image_url

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
        # Explicit opt-in keeps existing installations safe until a worker
        # service is provisioned; the durable queue lives in PostgreSQL.
        if os.getenv("EDITORIAL_ASYNC_ENABLED", "").lower() == "true":
            try:
                run, created = await run_in_threadpool(
                    store.enqueue, identity.tenant, identity.actor,
                    idempotency_key, brief.model_dump()
                )
            except RunConflict:
                raise HTTPException(409, "Clé d'idempotence déjà utilisée pour une autre demande.") from None
            except WorkerOffline:
                raise HTTPException(503, "Worker éditorial indisponible : aucun traitement ajouté à la file.") from None
            except psycopg.Error:
                raise HTTPException(503, "Persistance éditoriale indisponible.") from None
            if run["status"] in {"queued", "running"}:
                code = 202
            elif run["status"] == "failed":
                code = 422
            else:
                code = 200
            return JSONResponse(run, status_code=code)
        if not generation_gate.acquire(blocking=False):
            raise HTTPException(429, "Génération déjà en cours : capacité temporairement atteinte.",
                                headers={"Retry-After": "30"})
        try:
            try:
                run, created = await run_workflow(store, identity.tenant, identity.actor,
                                                 idempotency_key, brief, client, os.getenv("LLM_BASE_URL", ""))
            except RunConflict:
                raise HTTPException(409, "Clé d'idempotence déjà utilisée pour une autre demande.") from None
            except psycopg.Error:
                raise HTTPException(503, "Persistance éditoriale indisponible.") from None
        finally:
            generation_gate.release()
        code = 201 if created else (202 if run["status"] in {"queued", "running"} else 200)
        if run["status"] == "failed":
            code = {"provider_configuration": 503, "provider_timeout": 504,
                    "provider_unavailable": 502}.get(run.get("error_code"), 422)
        return JSONResponse(run, status_code=code)

    @router.get("/runs")
    async def list_runs(limit: int = Query(default=20, ge=1, le=50),
                        before: UUID | None = Query(default=None),
                        identity: Identity = Depends(get_identity),
                        store: PostgresStore = Depends(get_store)):
        try:
            return await run_in_threadpool(store.list_runs, identity.tenant, limit, before)
        except RunMissing:
            raise HTTPException(404, "Curseur de pagination introuvable.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible.") from None

    @router.get("/runs/{run_id}")
    async def get_run(run_id: UUID, identity: Identity = Depends(get_identity),
                      store: PostgresStore = Depends(get_store)):
        try:
            return await run_in_threadpool(store.get, identity.tenant, run_id)
        except RunMissing:
            raise HTTPException(404, "Exécution introuvable.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible.") from None

    @router.post("/runs/{run_id}/reconcile")
    async def reconcile_run(run_id: UUID, identity: Identity = Depends(get_identity),
                            store: PostgresStore = Depends(get_store)):
        """Manual recovery only; never retry the LLM and never touch active runs."""
        try:
            return await run_in_threadpool(store.reconcile_interrupted, identity.tenant, identity.actor, run_id)
        except RunMissing:
            raise HTTPException(404, "Exécution introuvable.") from None
        except RunConflict:
            raise HTTPException(409, "État modifié pendant la vérification.") from None
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

    @router.get("/runs/{run_id}/visuals")
    async def get_visuals(run_id: UUID, identity: Identity = Depends(get_identity),
                          store: PostgresStore = Depends(get_store)):
        try:
            return await run_in_threadpool(store.visual_plan, identity.tenant, run_id)
        except RunMissing:
            raise HTTPException(404, "Histoire introuvable.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible.") from None

    @router.post("/runs/{run_id}/scenes/{scene_number}/image")
    async def generate_image(run_id: UUID, scene_number: int,
                             identity: Identity = Depends(get_identity),
                             store: PostgresStore = Depends(get_store),
                             client=Depends(get_llm_client)):
        # Images require a separate, explicitly configured provider. Qwen is
        # text-only here. One scene is initiated by an explicit user action.
        base = os.getenv("IMAGE_BASE_URL", "")
        if not private_image_url(base):
            raise HTTPException(503, "Générateur d'images privé non configuré.")
        if not image_gate.acquire(blocking=False):
            raise HTTPException(429, "Génération d'image occupée.",
                                headers={"Retry-After": "30"})
        try:
            try:
                plan = await run_in_threadpool(store.visual_plan, identity.tenant, run_id)
                if not plan["approved"]:
                    raise HTTPException(409, "Le scénario doit être approuvé avant les images.")
                if scene_number < 1 or scene_number > len(plan["scenes"]):
                    raise HTTPException(404, "Scène introuvable.")
                scene = plan["scenes"][scene_number - 1]
                # Refuse an unconfigured storage location before claiming the job.
                await run_in_threadpool(media_preflight, identity.tenant, run_id, UUID(scene["scene_id"]))
                scene_id, _ = await run_in_threadpool(
                    store.begin_image, identity.tenant, identity.actor,
                    run_id, scene_number, scene["prompt"], UUID(scene["scene_id"]))
            except RunMissing:
                raise HTTPException(404, "Scène introuvable.") from None
            except RunConflict:
                raise HTTPException(409, "Image déjà demandée ou scénario modifié.") from None
            except ImageUnavailable:
                raise HTTPException(503, "Stockage privé des images indisponible.") from None
            except psycopg.Error:
                raise HTTPException(503, "Persistance éditoriale indisponible.") from None

            started = time.monotonic()
            try:
                png = await render_png(client, base, scene["prompt"])
                width, height = validate_png(png)
                path = await run_in_threadpool(save_png, identity.tenant, run_id, scene_id, png)
                try:
                    return JSONResponse(await run_in_threadpool(
                        store.finish_image, identity.tenant, identity.actor,
                        run_id, scene_id, width=width, height=height,
                        duration_seconds=round(time.monotonic() - started, 6),
                        png_sha256=hashlib.sha256(png).hexdigest(), byte_count=len(png),
                        storage=path if isinstance(path, dict) else None
                    ), status_code=201)
                except (RunConflict, RunMissing, psycopg.Error):
                    # A DB commit can succeed even if its acknowledgement is lost.
                    # Preserve the private file for explicit reconciliation.
                    raise HTTPException(503, "État de l'image non confirmé : intervention requise.") from None
            except ImageUnavailable as exc:
                try:
                    await run_in_threadpool(store.finish_image, identity.tenant,
                                            identity.actor, run_id, scene_id,
                                            error_code=exc.code,
                                            duration_seconds=round(time.monotonic() - started, 6))
                except (RunConflict, RunMissing, psycopg.Error):
                    raise HTTPException(503, "Résultat d'image incertain : intervention requise.") from None
                if exc.code in {"image_provider_timeout", "image_provider_response_uncertain", "image_storage_result_uncertain"}:
                    raise HTTPException(504 if exc.code == "image_provider_timeout" else 502,
                                        "Résultat d'image incertain : vérifiez le moteur avant toute reprise.") from None
                raise HTTPException(502, "Génération d'image échouée, sans rejeu automatique.") from None
        finally:
            image_gate.release()

    @router.get("/runs/{run_id}/visuals/verification")
    async def verify_images(run_id: UUID,
                            expected_scenes: int = Query(default=3, ge=1, le=6),
                            identity: Identity = Depends(get_identity),
                            store: PostgresStore = Depends(get_store)):
        from editorial.image_verification import verify_scene, verification_report
        try:
            plan = await run_in_threadpool(store.visual_plan, identity.tenant, run_id)
            counts = await run_in_threadpool(store.image_audit_counts, identity.tenant, run_id)
            checks = []
            for scene in plan["scenes"]:
                png = None
                if plan["approved"] and scene["image_status"] == "ready":
                    try:
                        scene_id, storage = await run_in_threadpool(store.image_asset, identity.tenant,
                                                                    run_id, scene["scene_number"], True)
                        png = await run_in_threadpool(load_png, identity.tenant, run_id, scene_id, storage)
                    except ImageUnavailable:
                        pass
                checks.append(verify_scene(scene, png, counts.get(scene["scene_id"], 0)))
            return verification_report(plan, checks, expected_scenes)
        except RunMissing:
            raise HTTPException(404, "Histoire introuvable.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible.") from None

    @router.get("/runs/{run_id}/scenes/{scene_number}/image")
    async def download_image(run_id: UUID, scene_number: int,
                             identity: Identity = Depends(get_identity),
                             store: PostgresStore = Depends(get_store)):
        try:
            scene_id, storage = await run_in_threadpool(store.image_asset, identity.tenant, run_id, scene_number, True)
            png = await run_in_threadpool(load_png, identity.tenant, run_id, scene_id, storage)
            return Response(png, media_type="image/png", headers={
                "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'"
            })
        except (RunMissing, ImageUnavailable):
            raise HTTPException(404, "Image privée introuvable.") from None
        except psycopg.Error:
            raise HTTPException(503, "Persistance éditoriale indisponible.") from None

    return router

