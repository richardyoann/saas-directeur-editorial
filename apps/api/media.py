"""Media HTTP routes: authentication, validation and explicit error translation."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from apps.api.dependencies import build_image_service, build_media_reader
from editorial.media.contracts import (
    Identity, ImageRequest, MediaOperationError, PersistenceUnavailable, RunMissing,
)
from editorial.media_rules import ImagePromptTooLong, ImageUnavailable


GENERATION_ERRORS = {
    'provider_unconfigured': (503, "Générateur d'images privé non configuré."),
    'capacity_busy': (429, "Génération d'image occupée."),
    'approval_required': (409, "Le scénario doit être approuvé avant les images."),
    'scene_missing': (404, "Scène introuvable."),
    'prompt_too_long': (422, "Descriptions visuelles trop longues : réduisez les portraits ou la scène."),
    'reservation_conflict': (409, "Image déjà demandée ou scénario modifié."),
    'storage_unavailable': (503, "Stockage privé des images indisponible."),
    'persistence_unavailable': (503, "Persistance éditoriale indisponible."),
    'commit_uncertain': (503, "État de l'image non confirmé : intervention requise."),
    'failure_uncertain': (503, "Résultat d'image incertain : intervention requise."),
}


def generation_error(error):
    if error.code in GENERATION_ERRORS:
        status, detail = GENERATION_ERRORS[error.code]
    elif error.code in {'image_provider_timeout', 'image_provider_response_uncertain', 'image_storage_result_uncertain'}:
        status = 504 if error.code == 'image_provider_timeout' else 502
        detail = "Résultat d'image incertain : vérifiez le moteur avant toute reprise."
    else:
        status, detail = 502, "Génération d'image échouée, sans rejeu automatique."
    return HTTPException(status, detail,
                         headers={'Retry-After': '30'} if error.code == 'capacity_busy' else None)


def create_media_router(get_identity, get_store, get_llm_client):
    router = APIRouter()

    @router.get('/runs/{run_id}/media')
    async def list_media(run_id: UUID, identity: Identity = Depends(get_identity), store=Depends(get_store)):
        try:
            return {'run_id': str(run_id), 'media': await build_media_reader(store).catalog(identity, run_id)}
        except RunMissing:
            raise HTTPException(404, 'Histoire introuvable.') from None
        except PersistenceUnavailable:
            raise HTTPException(503, 'Catalogue média indisponible.') from None

    @router.get('/runs/{run_id}/visuals')
    async def get_visuals(run_id: UUID, identity: Identity = Depends(get_identity), store=Depends(get_store)):
        try:
            return await build_media_reader(store).plan(identity, run_id)
        except ImagePromptTooLong:
            raise HTTPException(422, GENERATION_ERRORS['prompt_too_long'][1]) from None
        except RunMissing:
            raise HTTPException(404, 'Histoire introuvable.') from None
        except PersistenceUnavailable:
            raise HTTPException(503, 'Persistance éditoriale indisponible.') from None

    @router.post('/runs/{run_id}/scenes/{scene_number}/image')
    async def generate_image(run_id: UUID, scene_number: int, identity: Identity = Depends(get_identity),
                             store=Depends(get_store), client=Depends(get_llm_client)):
        try:
            result = await build_image_service(store, client).execute(identity, ImageRequest(run_id, scene_number))
            return JSONResponse(result, status_code=201)
        except MediaOperationError as error:
            raise generation_error(error) from None

    @router.get('/runs/{run_id}/visuals/verification')
    async def verify_images(run_id: UUID, expected_scenes: int = Query(default=3, ge=1, le=6),
                            identity: Identity = Depends(get_identity), store=Depends(get_store)):
        try:
            return await build_media_reader(store).verify(identity, run_id, expected_scenes)
        except RunMissing:
            raise HTTPException(404, 'Histoire introuvable.') from None
        except PersistenceUnavailable:
            raise HTTPException(503, 'Persistance éditoriale indisponible.') from None

    @router.get('/runs/{run_id}/scenes/{scene_number}/image')
    async def download_image(run_id: UUID, scene_number: int, identity: Identity = Depends(get_identity),
                             store=Depends(get_store)):
        try:
            png = await build_media_reader(store).download(identity, run_id, scene_number)
            return Response(png, media_type='image/png', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                                                                   'Content-Security-Policy': "default-src 'none'"})
        except (RunMissing, ImageUnavailable):
            raise HTTPException(404, 'Image privée introuvable.') from None
        except PersistenceUnavailable:
            raise HTTPException(503, 'Persistance éditoriale indisponible.') from None

    return router
