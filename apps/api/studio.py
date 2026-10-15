"""Private browser facade for editorial API. No bearer token enters client code.
One-process volatile sessions; require HTTPS for remote use.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response

router = APIRouter(prefix="/studio", include_in_schema=False)
ASSETS = Path(__file__).resolve().parents[1] / "web"
COOKIE = "editorial_studio_session"
TTL = 8 * 3600
sessions = {}
failures = {}

@dataclass
class Session:
    csrf: str
    until: float

def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    return response

def transport(request):
    if request.url.scheme == "https":
        return
    hostname = request.url.hostname or ""
    peer = request.client.host if request.client else ""
    if hostname not in {"localhost", "127.0.0.1", "::1"} or peer not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "HTTPS requis hors de la boucle locale.")

def origin(request):
    if request.headers.get("origin") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Origine refusée.")

def configured():
    password = os.getenv("EDITORIAL_WEB_PASSWORD", "")
    token = os.getenv("EDITORIAL_API_TOKEN", "")
    try:
        return len(password) >= 32 and len(token) >= 32 and not hmac.compare_digest(password.encode(), token.encode())
    except UnicodeEncodeError:
        return False

def cleanup():
    now = time.monotonic()
    for key, session in list(sessions.items()):
        if session.until < now:
            sessions.pop(key, None)
    for peer, values in list(failures.items()):
        values = [v for v in values if v > now - 900]
        if values: failures[peer] = values
        else: failures.pop(peer, None)

def session(request):
    transport(request)
    cleanup()
    cookie = request.cookies.get(COOKIE, "")
    item = sessions.get(hashlib.sha256(cookie.encode()).hexdigest()) if len(cookie) >= 32 else None
    if item is None:
        raise HTTPException(401, "Session absente ou expirée.")
    return hashlib.sha256(cookie.encode()).hexdigest(), item

def mutation(request):
    origin(request)
    key, item = session(request)
    if not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), item.csrf.encode()):
        raise HTTPException(403, "Protection CSRF invalide.")
    return key

async def body(request):
    raw = await request.body()
    if len(raw) > 64000:
        raise HTTPException(413, "Requête trop volumineuse.")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise HTTPException(422, "JSON invalide.") from None
    if not isinstance(value, dict):
        raise HTTPException(422, "Objet JSON attendu.")
    return value

@router.get("")
@router.get("/")
async def index(request: Request):
    transport(request)
    return no_store(FileResponse(ASSETS / "studio.html", media_type="text/html"))

@router.get("/assets/{name}")
async def asset(request: Request, name: Literal["studio.css", "studio.js"]):
    transport(request)
    return no_store(FileResponse(ASSETS / name, media_type="text/css" if name.endswith(".css") else "text/javascript"))

@router.get("/session")
async def status(request: Request):
    try:
        _, item = session(request)
    except HTTPException as exc:
        if exc.status_code != 401: raise
        return no_store(JSONResponse({"authenticated": False}))
    return no_store(JSONResponse({"authenticated": True, "csrf": item.csrf}))

@router.post("/session")
async def login(request: Request):
    transport(request)
    origin(request)
    if not configured():
        raise HTTPException(503, "Mot de passe web ou identifiants API non configurés.")
    cleanup()
    peer = request.client.host if request.client else "unknown"
    if len(failures.get(peer, [])) >= 5:
        raise HTTPException(429, "Trop de tentatives, réessayez plus tard.")
    supplied = (await body(request)).get("password")
    password = os.environ["EDITORIAL_WEB_PASSWORD"]
    if isinstance(supplied, str):
        try:
            supplied.encode("utf-8")
        except UnicodeEncodeError:
            raise HTTPException(422, "Mot de passe UTF-8 invalide.") from None
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied.encode(), password.encode()):
        failures.setdefault(peer, []).append(time.monotonic())
        raise HTTPException(401, "Mot de passe incorrect.")
    failures.pop(peer, None)
    if len(sessions) >= 64:
        raise HTTPException(503, "Trop de sessions actives.")
    opaque = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    sessions[hashlib.sha256(opaque.encode()).hexdigest()] = Session(csrf, time.monotonic() + TTL)
    response = no_store(JSONResponse({"authenticated": True, "csrf": csrf}))
    response.set_cookie(COOKIE, opaque, max_age=TTL, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", path="/studio")
    return response

@router.post("/logout")
async def logout(request: Request):
    key = mutation(request)
    sessions.pop(key, None)
    response = no_store(JSONResponse({"authenticated": False}))
    response.delete_cookie(COOKIE, path="/studio")
    return response

async def relay(request, method, path, payload=None, headers=None):
    if method == "GET":
        session(request)
    else:
        mutation(request)
    if not configured():
        raise HTTPException(503, "Accès privé non configuré.")
    auth = {"Authorization": "Bearer " + os.environ["EDITORIAL_API_TOKEN"]}
    auth.update(headers or {})
    try:
        shared = getattr(request.app.state, "internal_client", None)
        if shared is not None:
            result = await shared.request(method, path, headers=auth, json=payload)
        else:
            # Unit tests without lifespan retain the same ASGI behavior.
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=request.app), base_url="http://internal",
                timeout=275, trust_env=False
            ) as client:
                result = await client.request(method, path, headers=auth, json=payload)
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(502, "API éditoriale indisponible.") from None
    try:
        data = result.json()
    except ValueError:
        raise HTTPException(502, "Réponse API invalide.") from None
    return no_store(JSONResponse(data, status_code=result.status_code))

@router.get("/api/runs")
async def list_runs(request: Request, limit: int = Query(20, ge=1, le=50), before: UUID | None = None):
    path = f"/editorial/runs?limit={limit}"
    if before is not None: path += f"&before={before}"
    return await relay(request, "GET", path)

@router.post("/api/runs")
async def create_run(request: Request):
    mutation(request)
    try:
        key = str(UUID(request.headers.get("idempotency-key", "")))
    except ValueError:
        raise HTTPException(422, "Idempotency-Key UUID requis.") from None
    return await relay(request, "POST", "/editorial/runs", await body(request), {"Idempotency-Key": key})

@router.get("/api/runs/{run_id}")
async def get_run(request: Request, run_id: UUID):
    return await relay(request, "GET", f"/editorial/runs/{run_id}")

@router.post("/api/runs/{run_id}/reconcile")
async def reconcile(request: Request, run_id: UUID):
    return await relay(request, "POST", f"/editorial/runs/{run_id}/reconcile")

@router.get("/api/runs/{run_id}/history")
async def history(request: Request, run_id: UUID):
    return await relay(request, "GET", f"/editorial/runs/{run_id}/history")

@router.get("/api/runs/{run_id}/reviews")
async def reviews(request: Request, run_id: UUID, limit: int = Query(20, ge=1, le=50),
                  before_revision: int | None = Query(None, ge=1, le=2147483647)):
    path = f"/editorial/runs/{run_id}/reviews?limit={limit}"
    if before_revision is not None: path += f"&before_revision={before_revision}"
    return await relay(request, "GET", path)

@router.get("/api/runs/{run_id}/visuals")
async def visual_plan(request: Request, run_id: UUID):
    return await relay(request, "GET", f"/editorial/runs/{run_id}/visuals")

@router.post("/api/runs/{run_id}/scenes/{scene_number}/image")
async def image_generate(request: Request, run_id: UUID, scene_number: int):
    if scene_number < 1 or scene_number > 6:
        raise HTTPException(404, "Scène introuvable.")
    return await relay(request, "POST", f"/editorial/runs/{run_id}/scenes/{scene_number}/image")

@router.get("/api/runs/{run_id}/scenes/{scene_number}/image")
async def image_view(request: Request, run_id: UUID, scene_number: int):
    # Private image data is streamed through the session facade, never served
    # from /media or a public/static directory.
    session(request)
    if not configured():
        raise HTTPException(503, "Accès privé non configuré.")
    if scene_number < 1 or scene_number > 6:
        raise HTTPException(404, "Image introuvable.")
    path = f"/editorial/runs/{run_id}/scenes/{scene_number}/image"
    auth = {"Authorization": "Bearer " + os.environ["EDITORIAL_API_TOKEN"]}
    try:
        shared = getattr(request.app.state, "internal_client", None)
        if shared is not None:
            result = await shared.get(path, headers=auth)
        else:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=request.app),
                                         base_url="http://internal", timeout=15,
                                         trust_env=False) as client:
                result = await client.get(path, headers=auth)
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(502, "Image privée indisponible.") from None
    if result.status_code != 200 or result.headers.get("content-type", "").split(";")[0] != "image/png":
        raise HTTPException(404, "Image privée introuvable.")
    if len(result.content) > 4 * 1024 * 1024:
        raise HTTPException(502, "Image privée trop volumineuse.")
    return no_store(Response(content=result.content, media_type="image/png"))

@router.post("/api/runs/{run_id}/steps/{step}/review")
async def review(request: Request, run_id: UUID, step: Literal["analysis", "storyboard"]):
    mutation(request)
    return await relay(request, "POST", f"/editorial/runs/{run_id}/steps/{step}/review", await body(request))
