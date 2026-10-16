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
    return len(password) >= 32 and len(token) >= 32 and not hmac.compare_digest(password, token)

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
    if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), item.csrf):
        raise HTTPException(403, "Protection CSRF invalide.")
    return key

async def body(request):
    raw = await request.body()
    if len(raw) > 64000:
        raise HTTPException(413, "Requête trop volumineuse.")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
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

@router.get("/api/runs/{run_id}/visuals/verification")
async def image_verification(request: Request, run_id: UUID,
                             expected_scenes: int = Query(3, ge=1, le=6)):
    return await relay(request, "GET",
                       f"/editorial/runs/{run_id}/visuals/verification?expected_scenes={expected_scenes}")

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


# Production control: GitHub calls are exclusively server-side, same-origin and session
# protected. Tokens are never returned to the browser or stored in story entities.
GH_REPO = "richardyoann/saas-directeur-editorial"
GH_API = "https://api.github.com/repos/" + GH_REPO


async def _gh(method: str, suffix: str, *, token: str, payload: dict | None = None):
    if len(token) < 32:
        raise HTTPException(503, "Intégration GitHub privée non configurée.")
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=12.0, trust_env=False) as client:
            response = await client.request(
                method, GH_API + suffix, headers=headers, json=payload
            )
    except (httpx.HTTPError, TimeoutError):
        raise HTTPException(502, "GitHub indisponible.") from None
    if response.status_code == 401:
        raise HTTPException(503, "Jeton GitHub non valide.")
    if response.status_code == 403:
        raise HTTPException(503, "GitHub refuse les permissions requises.")
    if response.status_code == 404:
        raise HTTPException(404, "Ressource GitHub introuvable.")
    if response.status_code >= 400:
        raise HTTPException(502, "Opération GitHub refusée.")
    if response.status_code == 204:
        return {}
    try:
        return response.json()
    except ValueError:
        raise HTTPException(502, "Réponse GitHub invalide.") from None


def _github_read_token():
    return os.getenv("EDITORIAL_GITHUB_READ_TOKEN", "")


def _github_write_token():
    if os.getenv("EDITORIAL_GITHUB_DELIVERY_WRITE_ENABLED") != "true":
        raise HTTPException(403, "Commandes de livraison PC désactivées.")
    token = os.getenv("EDITORIAL_GITHUB_WRITE_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "Jeton de contrôle de livraison absent.")
    return token


@router.get("/api/conception")
async def conception_data(request: Request):
    session(request)
    token = _github_read_token()
    import asyncio
    issues, pulls, delivery = await asyncio.gather(
        _gh("GET", "/issues?state=all&per_page=100", token=token),
        _gh("GET", "/pulls?state=all&per_page=70", token=token),
        _gh("GET", "/actions/workflows/local-delivery.yml/runs?per_page=70", token=token),
    )
    if not isinstance(issues, list) or not isinstance(pulls, list) or not isinstance(delivery, dict):
        raise HTTPException(502, "Données GitHub invalides.")
    epics = []
    for item in issues:
        if not isinstance(item, dict) or "pull_request" in item:
            continue
        title = str(item.get("title") or "")
        if not (title.startswith("[EPIC-") or title.startswith("Epic")):
            continue
        epics.append({
            "number": item.get("number"), "title": title,
            "state": item.get("state"), "created_at": item.get("created_at"),
            "closed_at": item.get("closed_at"),
            "url": item.get("html_url"),
        })
    prs = [{
        "number": item.get("number"), "title": item.get("title"),
        "state": item.get("state"), "draft": item.get("draft", False),
        "merged_at": item.get("merged_at"), "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"), "url": item.get("html_url"),
        "sha": (item.get("head") or {}).get("sha"),
        "merge_commit_sha": item.get("merge_commit_sha"),
    } for item in pulls if isinstance(item, dict)]
    jobs = [{
        "id": item.get("id"), "sha": item.get("head_sha"),
        "status": item.get("status"), "conclusion": item.get("conclusion"),
        "created_at": item.get("created_at"), "updated_at": item.get("updated_at"),
        "url": item.get("html_url"),
    } for item in delivery.get("workflow_runs", []) if isinstance(item, dict)]
    return no_store(JSONResponse({
        "epics": epics, "pull_requests": prs, "deliveries": jobs,
        "delivery_control_enabled": os.getenv("EDITORIAL_GITHUB_DELIVERY_WRITE_ENABLED") == "true"
    }))


@router.post("/api/conception/pulls/{pr_number}/deliver")
async def approve_pc_delivery(request: Request, pr_number: int):
    """Owner-only explicit approval of the immutable, already merged main SHA.

    Never merge a PR or modify the code from this endpoint. Before dispatching,
    require a successful push regression and an identical current main SHA.
    """
    mutation(request)
    if pr_number < 1 or pr_number > 1_000_000:
        raise HTTPException(422, "Numéro PR invalide.")
    data = await body(request)
    if data.get("confirm") != "AUTORISER PC" or set(data) != {"confirm", "sha"}:
        raise HTTPException(422, "Confirmation explicite requise.")
    expected = data.get("sha")
    import re
    if not isinstance(expected, str) or re.fullmatch(r"[a-f0-9]{40}", expected) is None:
        raise HTTPException(422, "SHA exact requis.")
    token = _github_write_token()
    pr = await _gh("GET", f"/pulls/{pr_number}", token=token)
    if (pr.get("state") != "closed" or not pr.get("merged_at")
            or (pr.get("base") or {}).get("ref") != "main"
            or pr.get("merge_commit_sha") != expected):
        raise HTTPException(409, "PR non fusionnée sur main ou SHA différent.")
    branch = await _gh("GET", "/branches/main", token=token)
    if (branch.get("commit") or {}).get("sha") != expected:
        raise HTTPException(409, "Ce SHA n'est plus la tête de main.")
    regression = await _gh(
        "GET", f"/actions/workflows/regression.yml/runs?head_sha={expected}&per_page=30",
        token=token,
    )
    verified = any(
        x.get("head_sha") == expected and x.get("head_branch") == "main"
        and x.get("event") == "push" and x.get("status") == "completed"
        and x.get("conclusion") == "success"
        for x in regression.get("workflow_runs", [])
    )
    if not verified:
        raise HTTPException(409, "Régression complète réussie obligatoire.")
    # GitHub repository Actions variable used by the existing local-delivery
    # workflow. A limited-permission token, role policy and explicit opt-in
    # are deployment prerequisites; no browser token can reach this endpoint.
    await _gh("PATCH", "/actions/variables/LOCAL_PC_APPROVED_SHA",
              token=token, payload={"name": "LOCAL_PC_APPROVED_SHA", "value": expected})
    await _gh("POST", "/actions/workflows/local-delivery.yml/dispatches",
              token=token, payload={"ref": "main", "inputs": {"approved_sha": expected}})
    return no_store(JSONResponse({
        "requested": True, "pr_number": pr_number, "sha": expected,
        "message": "Livraison demandée. Vérifier le résultat du runner PC dans GitHub Actions."
    }))
