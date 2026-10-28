"""Production voice/video HTTP routes: validation and explicit error translation."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from apps.api.dependencies import (
    build_media_stream, build_video_service, build_voice_service,
)
from editorial.media.contracts import (
    Identity, PersistenceUnavailable, RunConflict, RunMissing,
)
from infrastructure.media.production_media import ProductionStorageError
from production.media_pipeline import ProductionMediaError

MEDIA_ERRORS = {
    "approval_required": (409, "Le scénario doit être approuvé avant la voix et la vidéo."),
    "storyboard_duration_invalid": (409, "Un storyboard approuvé de 75 secondes est requis."),
    "media_incomplete": (409, "Toutes les images et la voix doivent être disponibles avant le montage."),
    "media_capacity_busy": (429, "Production média déjà en cours."),
    "voice_provider_unconfigured": (503, "Synthèse vocale privée non configurée."),
    "video_provider_unconfigured": (503, "Montage vidéo privé non configuré."),
    "voice_generation_failed": (502, "Synthèse vocale échouée, sans rejeu automatique."),
    "video_render_failed": (502, "Montage vidéo échoué, sans rejeu automatique."),
    "production_media_directory_invalid": (503, "Répertoire de production privé indisponible."),
    "media_storage_unavailable": (503, "Stockage privé des médias indisponible."),
    "media_kind_invalid": (404, "Média introuvable."),
}
MEDIA_TYPES = {"voice": "audio/wav", "video": "video/mp4", "subtitles": "application/x-subrip"}


def media_error(error):
    status, detail = MEDIA_ERRORS.get(error.code, (502, "Production média échouée."))
    headers = {"Retry-After": "30"} if error.code == "media_capacity_busy" else None
    return HTTPException(status, detail, headers=headers)


def create_production_media_router(get_identity, get_store):
    router = APIRouter()

    @router.get("/runs/{run_id}/production-media")
    async def production_plan(run_id: UUID, identity: Identity = Depends(get_identity),
                              store=Depends(get_store)):
        try:
            return await build_media_stream(store).plan(identity, run_id)
        except RunMissing:
            raise HTTPException(404, "Histoire introuvable.") from None
        except (RunConflict, PersistenceUnavailable):
            raise HTTPException(503, "Production média indisponible.") from None

    @router.post("/runs/{run_id}/voice")
    async def generate_voice(run_id: UUID, identity: Identity = Depends(get_identity),
                             store=Depends(get_store)):
        try:
            return await build_voice_service(store).execute(identity, run_id)
        except ProductionMediaError as error:
            raise media_error(error) from None
        except (RunMissing, RunConflict):
            raise HTTPException(409, "Génération vocale déjà en cours ou indisponible.") from None
        except (PersistenceUnavailable, ProductionStorageError):
            raise HTTPException(503, "Production vocale indisponible.") from None

    @router.post("/runs/{run_id}/video")
    async def generate_video(run_id: UUID, identity: Identity = Depends(get_identity),
                             store=Depends(get_store)):
        try:
            return await build_video_service(store).execute(identity, run_id)
        except ProductionMediaError as error:
            raise media_error(error) from None
        except (RunMissing, RunConflict):
            raise HTTPException(409, "Montage déjà en cours ou média déjà disponible.") from None
        except (PersistenceUnavailable, ProductionStorageError):
            raise HTTPException(503, "Montage vidéo indisponible.") from None

    @router.get("/runs/{run_id}/media/{media_id}/content")
    async def media_content(run_id: UUID, media_id: UUID,
                            download: bool = Query(False),
                            identity: Identity = Depends(get_identity),
                            store=Depends(get_store)):
        try:
            media = await build_media_stream(store).read(identity, run_id, media_id)
        except ProductionMediaError as error:
            raise media_error(error) from None
        except RunMissing:
            raise HTTPException(404, "Média introuvable.") from None
        except (RunConflict, PersistenceUnavailable):
            raise HTTPException(503, "Média indisponible.") from None
        kind = media["kind"]
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        if download:
            name = f"arvor-{kind}-{str(run_id)[:8]}{'.wav' if kind == 'voice' else '.mp4' if kind == 'video' else '.srt'}"
            headers["Content-Disposition"] = f'attachment; filename="{name}"'
        return FileResponse(media["path"], media_type=MEDIA_TYPES.get(kind, "application/octet-stream"),
                            headers=headers,
                            background=BackgroundTask(media["directory"].cleanup))

    return router
