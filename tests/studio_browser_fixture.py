"""Disposable API stub for real-browser Studio journey tests.

This module is used only by the browser CI tests, never by the runtime.
No real PostgreSQL, Qwen, or persistent user data.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from editorial.models import Analysis, Brief, ReviewDecision, Storyboard
from apps.api.studio import router, sessions, failures

app = FastAPI()
app.include_router(router)
runs = {}
keys = {}
events = {}
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
    return record


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
    if record["status"] not in {"waiting_validation", "changes_requested"} or (
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
