"""Disposable API stub for real-browser Studio journey tests.

This module is used only by the browser CI tests, never by the runtime.
No real PostgreSQL, Qwen, or persistent user data.
"""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from editorial.models import Analysis, Brief, ReviewDecision, Storyboard
from editorial.visuals import characters, image_prompt
from apps.api.studio import router, sessions, failures

app = FastAPI()
app.include_router(router)
runs = {}
keys = {}
events = {}
image_states = {}
IMAGE_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
call_count = {"review": 0, "generate": 0}


def clock():
    return datetime.now(timezone.utc).isoformat()


def scene(number, seconds):
    return {
        "title": "Scène " + str(number), "duration_seconds": seconds,
        "narration": "Une légende bretonne se raconte.",
        "visual_description": "Brume sur la côte bretonne",
        "characters": ["Un marin"], "landscape": "Côte bretonne",
        "colors": ["bleu", "vert"], "shot": "Plan large",
        "emotion": "Mystère", "sound": "Vagues",
        "image_prompt": "La Bretagne et sa côte brumeuse",
    }


def require_token(authorization):
    if authorization != "Bearer " + "t" * 48:
        raise HTTPException(401)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/__fixture__/reset")
def reset():
    runs.clear()
    keys.clear()
    events.clear()
    image_states.clear()
    sessions.clear()
    failures.clear()
    call_count.update(review=0, generate=0)
    return {"reset": True}


@app.post("/__fixture__/stale/{run_id}")
def stale(run_id: UUID):
    run = get_record(run_id)
    run["status"] = "running"
    run["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    return {"status": run["status"]}


@app.get("/__fixture__/counts")
def counts():
    return call_count.copy()


@app.get("/editorial/runs")
def listing(limit: int = Query(20, ge=1, le=50), before: UUID | None = None,
            authorization: str = Header("")):
    require_token(authorization)
    values = sorted(runs.values(), key=lambda r: (r["created_at"], r["id"]), reverse=True)
    if before is not None:
        index = next((i for i, r in enumerate(values) if r["id"] == str(before)), None)
        if index is None:
            raise HTTPException(404)
        values = values[index + 1:]
    page = values[:limit]
    return {"runs": [{
        "id": r["id"], "topic": r["brief"]["topic"], "title": r["storyboard"]["title"],
        "status": r["status"], "created_at": r["created_at"],
        "review_revision": r.get("review_revision", 0),
    } for r in page], "next_before": page[-1]["id"] if len(values) > limit else None}


@app.post("/editorial/runs")
def generate(brief: Brief, authorization: str = Header(""),
             idempotency_key: UUID = Header()):
    require_token(authorization)
    key = str(idempotency_key)
    if key in keys:
        stored = runs[keys[key]]
        if stored["brief"] != brief.model_dump():
            raise HTTPException(409)
        if stored["status"] == "failed":
            return JSONResponse(stored, status_code=422)
        return stored
    run_id = str(uuid4())
    count = brief.scene_count
    total = brief.duration_seconds
    scenes = [scene(i + 1, total // count + (i < total % count)) for i in range(count)]
    now = clock()
    record = {
        "id": run_id, "brief": brief.model_dump(), "status": "waiting_validation",
        "created_at": now, "updated_at": now, "review_revision": 0,
        "requires_human_validation": True,
        "analysis": {"angle": "Un récit entre légende et mémoire",
                     "message": "Développer un récit accessible",
                     "historical_checks": ["Vérifier les sources historiques"]},
        "storyboard": {"title": brief.topic, "synopsis": "Conte breton illustré",
                       "cast": [{"name": "Un marin", "appearance": "Manteau de laine rouge et barbe grise",
                                 "personality": "Courageux", "role": "Témoin"}],
                       "scenes": scenes},
        "reviews": {},
    }
    runs[run_id] = record
    keys[key] = run_id
    events[run_id] = []
    call_count["generate"] += 1
    if brief.topic == "Asynchrone simulée":
        record["status"] = "queued"
        record["_test_polls"] = 0
        return JSONResponse(record, status_code=202)
    if brief.topic == "Erreur IA simulée":
        record.update(status="failed", error_code="invalid_structured_output")
        return JSONResponse(record, status_code=422)
    return record


def get_record(run_id):
    record = runs.get(str(run_id))
    if record is None:
        raise HTTPException(404)
    return record


@app.get("/editorial/runs/{run_id}")
def detail(run_id: UUID, authorization: str = Header("")):
    require_token(authorization)
    record = get_record(run_id)
    if record.get("status") in {"queued", "running"} and record.get("_test_polls") is not None:
        record["_test_polls"] += 1
        if record["_test_polls"] >= 2:
            record["status"] = "running"
        if record["_test_polls"] >= 3:
            record["status"] = "waiting_validation"
    from editorial.store import recovery_status
    return record | {"recovery": recovery_status(record)}


@app.post("/editorial/runs/{run_id}/reconcile")
def reconcile(run_id: UUID, authorization: str = Header("")):
    require_token(authorization)
    run = get_record(run_id)
    if (run["status"] == "running"
            and (datetime.now(timezone.utc) - datetime.fromisoformat(run["updated_at"])).total_seconds() > 600):
        run.update(status="failed", error_code="run_interrupted", updated_at=clock())
    return run


@app.get("/editorial/runs/{run_id}/history")
def history(run_id: UUID, authorization: str = Header("")):
    require_token(authorization)
    record = get_record(run_id)
    return {"run_id": record["id"], "steps": [
        {"order": 0, "prompt": "Analyse : " + record["brief"]["topic"],
         "parsed": record["analysis"]},
        {"order": 1, "prompt": "Storyboard : " + record["brief"]["topic"],
         "parsed": record["storyboard"]},
    ]}


@app.get("/editorial/runs/{run_id}/media")
def media_catalog(run_id: UUID, authorization: str = Header("")):
    require_token(authorization)
    get_record(run_id)
    return {"run_id": str(run_id), "media": []}


@app.get("/editorial/runs/{run_id}/visuals")
def visuals(run_id: UUID, authorization: str = Header("")):
    require_token(authorization)
    record = get_record(run_id)
    board = record.get("storyboard")
    if not board or record.get("storyboard_stale"):
        return {"run_id": str(run_id), "approved": False, "characters": [], "scenes": []}
    return {"run_id": str(run_id), "approved": record["status"] == "approved",
            "characters": characters(board),
            "scenes": [
                {"scene_number": n, "scene_id": str(n), "title": scene["title"],
                 "prompt": image_prompt(record, n),
                 "image_status": image_states.get((str(run_id), n), "not_generated"),
                 "generation": {"duration_seconds": 1.25, "outcome_uncertain": False,
                                "provenance": {"character_reference_sha256": "fixture"}}
                    if (str(run_id), n) in image_states else None}
                for n, scene in enumerate(board["scenes"], 1)
            ]}


@app.get("/editorial/runs/{run_id}/visuals/verification")
def verify_images(run_id: UUID, expected_scenes: int = Query(3, ge=1, le=6),
                  authorization: str = Header("")):
    require_token(authorization)
    plan = visuals(run_id, authorization)
    return {"run_id": str(run_id), "expected_scenes": expected_scenes,
            "technical_passed": plan["approved"] and len(plan["scenes"]) == expected_scenes
                and all(s["image_status"] == "ready" for s in plan["scenes"]),
            "scenes": [{"passed": s["image_status"] == "ready"} for s in plan["scenes"]],
            "gpu_verified": False, "human_visual_review_required": True,
            "duplicate_image_digests": False}


@app.post("/editorial/runs/{run_id}/scenes/{scene_number}/image")
def generate_image(run_id: UUID, scene_number: int, authorization: str = Header("")):
    require_token(authorization)
    record = get_record(run_id)
    if record["status"] != "approved" or record.get("storyboard_stale"):
        raise HTTPException(409)
    if scene_number < 1 or scene_number > len(record["storyboard"]["scenes"]):
        raise HTTPException(404)
    key = (str(run_id), scene_number)
    if key in image_states:
        raise HTTPException(409)
    image_states[key] = "ready"
    return JSONResponse({"scene_number": scene_number, "status": "ready", "width": 1, "height": 1}, status_code=201)


@app.get("/editorial/runs/{run_id}/scenes/{scene_number}/image")
def get_image(run_id: UUID, scene_number: int, authorization: str = Header("")):
    require_token(authorization)
    get_record(run_id)
    if image_states.get((str(run_id), scene_number)) != "ready":
        raise HTTPException(404)
    return Response(IMAGE_BYTES, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/editorial/runs/{run_id}/reviews")
def reviews(run_id: UUID, limit: int = Query(20, ge=1, le=50),
            before_revision: int | None = Query(None, ge=1), authorization: str = Header("")):
    require_token(authorization)
    get_record(run_id)
    values = sorted(events[str(run_id)], key=lambda x: x["revision"], reverse=True)
    if before_revision:
        values = [r for r in values if r["revision"] < before_revision]
    page = values[:limit]
    return {"run_id": str(run_id), "reviews": page,
            "next_before_revision": page[-1]["revision"] if len(values) > limit else None}


@app.post("/editorial/runs/{run_id}/steps/{step}/review")
def review(run_id: UUID, step: str, decision: ReviewDecision,
           authorization: str = Header("")):
    require_token(authorization)
    if step not in {"analysis", "storyboard"}:
        raise HTTPException(422)
    record = get_record(run_id)
    if record["status"] not in {"waiting_validation", "changes_requested", "approved"} or (
        decision.expected_revision != record.get("review_revision", 0)
    ):
        raise HTTPException(409)
    if step == "storyboard" and record.get("storyboard_stale") and decision.action == "accept":
        raise HTTPException(409)
    if decision.action == "revise":
        try:
            model = (Analysis if step == "analysis" else Storyboard).model_validate(decision.revised_output)
            if step == "storyboard":
                model.validate_brief(Brief.model_validate(record["brief"]))
        except (TypeError, ValueError):
            raise HTTPException(422) from None
        record[step] = model.model_dump()
        if step == "analysis":
            record["storyboard_stale"] = True
            if "storyboard" in record["reviews"]:
                record["reviews"]["storyboard"]["valid"] = False
        else:
            record["storyboard_stale"] = False
    revision = record.get("review_revision", 0) + 1
    record["review_revision"] = revision
    record["reviews"][step] = {"action": decision.action, "valid": True}
    approved = not record.get("storyboard_stale") and all(
        record["reviews"].get(k, {}).get("action") == "accept"
        and record["reviews"].get(k, {}).get("valid")
        for k in ("analysis", "storyboard")
    )
    record["status"] = "approved" if approved else (
        "changes_requested" if decision.action in {"reject", "revise"} or
        record.get("storyboard_stale") else "waiting_validation"
    )
    record["requires_human_validation"] = not approved
    record["updated_at"] = clock()
    events[record["id"]].append({
        "revision": revision, "action": decision.action, "step": step,
        "comment": decision.comment, "created_at": clock(),
        "effective_output": deepcopy(record[step]),
    })
    call_count["review"] += 1
    return record
