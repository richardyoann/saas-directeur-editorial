"""Uses the existing po_* schema; never creates or migrates tables at startup."""
import hashlib
import json
import os
from pathlib import Path
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4, uuid5

import psycopg
from pilotage.audit import mutate
from editorial.models import Brief, Analysis, Storyboard, ReviewDecision
from editorial.worker_guard import WorkerOffline, worker_lock_id

WORKFLOW_VERSION = "editorial-v1.2"
# Conservative threshold: both provider calls have a 120s wall limit.
# This does not run automatically on reads; a user must request reconciliation.
INTERRUPTED_AFTER_SECONDS = 600


def interrupted(run, reference_time=None):
    if run.get("status") != "running":
        return False
    stamp = (run.get("current_step") or {}).get("started_at") or run.get("updated_at") or run.get("created_at")
    try:
        started = datetime.fromisoformat(stamp)
        if started.tzinfo is None:
            return False
        elapsed = ((reference_time or datetime.now(timezone.utc)) - started).total_seconds()
        return elapsed > INTERRUPTED_AFTER_SECONDS
    except (TypeError, ValueError, OverflowError):
        return False



def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(brief, actor_id):
    payload = {"brief": brief, "actor_id": str(actor_id), "workflow_version": WORKFLOW_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def runtime_code_version():
    # deploy_local binds immutable release directories and the service process.
    release = Path(__file__).resolve().parents[1].name
    match = re.fullmatch(r"([0-9a-f]{40})-[0-9]+", release)
    return match.group(1) if match else os.getenv("EDITORIAL_CODE_VERSION", "unidentified")


class RunConflict(Exception):
    pass


class RunMissing(Exception):
    pass


class ReviewInvalid(Exception):
    pass



def validated_review_output(step, output, brief):
    try:
        brief = Brief.model_validate(brief)
        result = (Analysis if step == "analysis" else Storyboard).model_validate(output)
        if step == "storyboard":
            result.validate_brief(brief)
        return result.model_dump()
    except (ValueError, TypeError):
        raise ReviewInvalid() from None


class PostgresStore:
    def __init__(self, database_url):
        self.database_url = database_url

    def connect(self):
        return psycopg.connect(self.database_url, connect_timeout=5)

    @staticmethod
    def _write(conn, tenant, actor, run_id, kind, entity_id, content, version=0):
        mutate(conn, tenant_id=tenant, actor_id=actor, kind=kind, entity_id=entity_id,
               operation="created" if version == 0 else "updated", expected_version=version,
               content=content, source_key=uuid4(), correlation_id=run_id)

    def start(self, tenant, actor, key, brief, *, queued=False):
        run_id = uuid5(tenant, "editorial-run:" + str(key))
        digest = fingerprint(brief, actor)
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,2))", (str(run_id),))
            row = conn.execute("SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' AND entity_id=%s AND NOT deleted", (tenant, run_id)).fetchone()
            if row:
                if row[0].get("request_hash") != digest:
                    raise RunConflict()
                return row[0], False
            if queued:
                # Fail closed for *new* jobs when no consumer holds its
                # session-level lock. Existing idempotency replays remain
                # readable when the worker is temporarily unavailable.
                available = conn.execute(
                    "SELECT pg_try_advisory_xact_lock(%s)", (worker_lock_id(tenant),)
                ).fetchone()[0]
                if available:
                    raise WorkerOffline()
            run = {"id": str(run_id), "type": "editorial_run", "workflow_version": WORKFLOW_VERSION,
                   "request_hash": digest, "brief": brief, "status": "queued" if queued else "running", "steps": [],
                   "code_version": runtime_code_version(),
                   "created_at": now(), "updated_at": now(), "requires_human_validation": True,
                   "run_owner_actor": str(actor)}
            self._write(conn, tenant, actor, run_id, "treatment", run_id, run)
            return run, True

    def enqueue(self, tenant, actor, key, brief):
        """Durable, idempotent insertion; queue entry and audit commit atomically."""
        return self.start(tenant, actor, key, brief, queued=True)

    def claim_queued(self, tenant, actor):
        """Atomically claim one queued run in the tenant without racing other workers.

        SKIP LOCKED guarantees two workers cannot claim the same run.
        The actor of the original request is recorded as run_owner_actor and
        used for all subsequent domain mutations and audits.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT entity_id, version, content FROM po_entity "
                "WHERE tenant_id=%s AND kind='treatment' AND NOT deleted "
                "AND content->>'type'='editorial_run' AND content->>'status'='queued' "
                "ORDER BY content->>'created_at' ASC, entity_id ASC "
                "LIMIT 1 FOR UPDATE SKIP LOCKED",
                (tenant,),
            ).fetchone()
            if not row:
                return None
            run_id, version, run = row
            if run["status"] != "queued":
                raise RunConflict()
            run["status"] = "running"
            run["claimed_at"] = now()
            run["updated_at"] = run["claimed_at"]
            run["worker_actor_id"] = str(actor)
            self._write(conn, tenant, actor, run_id, "treatment", run_id, run, version)
            return run

    def reconcile_interrupted(self, tenant, actor, run_id):
        """Operator-triggered recovery; never restart an ambiguous Qwen request.

        Row locking serializes the transition with save_step. Preserve an
        interruption snapshot and audit/outbox in the same DB transaction.
        """
        with self.connect() as conn:
            row = conn.execute(
                "SELECT version, content FROM po_entity WHERE tenant_id=%s "
                "AND kind='treatment' AND entity_id=%s AND NOT deleted FOR UPDATE",
                (tenant, run_id),
            ).fetchone()
            if not row or row[1].get("type") != "editorial_run":
                raise RunMissing()
            version, run = row
            if not interrupted(run):
                return run
            step = run.get("current_step")
            if step:
                treatment_id = UUID(step["treatment_id"])
                current = conn.execute(
                    "SELECT version, content FROM po_entity WHERE tenant_id=%s "
                    "AND kind='treatment' AND entity_id=%s AND NOT deleted FOR UPDATE",
                    (tenant, treatment_id),
                ).fetchone()
                if not current or current[1].get("status") != "running":
                    raise RunConflict()
                treatment_version, treatment = current
                finished = now()
                treatment.update(status="failed", error_code="run_interrupted", finished_at=finished)
                self._write(conn, tenant, actor, run_id, "treatment", treatment_id, treatment, treatment_version)
                # The prompt was saved at begin_step; retain the same diagnostic
                # shape as normal failed LLM calls without inventing an AI output.
                prompt = conn.execute(
                    "SELECT content->>'text' FROM po_entity WHERE tenant_id=%s "
                    "AND kind='prompt' AND entity_id=%s AND NOT deleted",
                    (tenant, UUID(step["prompt_id"])),
                ).fetchone()
                result_id = uuid5(run_id, step["name"] + ":result")
                self._write(conn, tenant, actor, run_id, "result", result_id,
                            {"run_id": str(run_id), "type": "editorial_step_snapshot",
                             "order": len(run["steps"]), "prompt_id": step["prompt_id"],
                             "treatment_id": str(treatment_id),
                             "prompt": prompt[0] if prompt else None, "prompt_version": "1.2.0",
                             "response_metadata": {}, "raw_response": None, "parsed": None,
                             "error_code": "run_interrupted"})
                run["steps"].append({"name": step["name"], "status": "failed",
                                     "treatment_id": str(treatment_id), "result_id": str(result_id)})
                run.pop("current_step", None)
            run.update(status="failed", error_code="run_interrupted",
                       updated_at=now(), requires_human_validation=True)
            self._write(conn, tenant, actor, run_id, "treatment", run_id, run, version)
            return run


    def get(self, tenant, run_id):
        with self.connect() as conn:
            row = conn.execute("SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' AND entity_id=%s AND NOT deleted", (tenant, run_id)).fetchone()
            if not row or row[0].get("type") != "editorial_run":
                raise RunMissing()
            return row[0]


    def list_runs(self, tenant, limit=20, before=None):
        """Tenant-scoped keyset pagination of editorial runs, without prompts."""
        with self.connect() as conn:
            anchor = None
            if before is not None:
                row = conn.execute(
                    "SELECT content->>'created_at' FROM po_entity "
                    "WHERE tenant_id=%s AND kind='treatment' AND entity_id=%s "
                    "AND content->>'type'='editorial_run' AND NOT deleted",
                    (tenant, before),
                ).fetchone()
                if not row:
                    raise RunMissing()
                anchor = row[0]
            query = (
                "SELECT entity_id, content->'brief'->>'topic', "
                "content->'storyboard'->>'title', content->>'status', "
                "content->>'created_at', content->>'updated_at', "
                "content->>'review_revision' FROM po_entity "
                "WHERE tenant_id=%s AND kind='treatment' "
                "AND content->>'type'='editorial_run' AND NOT deleted "
            )
            params = [tenant]
            if before is not None:
                query += "AND (content->>'created_at', entity_id) < (%s::text, %s::uuid) "
                params.extend((anchor, before))
            query += "ORDER BY content->>'created_at' DESC, entity_id DESC LIMIT %s"
            params.append(limit + 1)
            rows = conn.execute(query, params).fetchall()
            summaries = []
            for run_id, topic, title, status, created_at, updated_at, revision in rows[:limit]:
                summaries.append({
                    "id": str(run_id), "topic": topic or "",
                    "title": title or "", "status": status or "unknown",
                    "created_at": created_at, "updated_at": updated_at,
                    "review_revision": int(revision) if revision is not None else 0,
                })
            return {
                "runs": summaries,
                "next_before": summaries[-1]["id"] if len(rows) > limit else None,
            }

    def history(self, tenant, run_id):
        self.get(tenant, run_id)
        with self.connect() as conn:
            rows = conn.execute("SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' AND content->>'run_id'=%s AND content->>'type'='editorial_step_snapshot' AND NOT deleted ORDER BY (content->>'order')::integer", (tenant, str(run_id))).fetchall()
            return [row[0] for row in rows]

    def begin_step(self, tenant, actor, run_id, step, prompt):
        with self.connect() as conn:
            row = conn.execute("SELECT version,content FROM po_entity WHERE tenant_id=%s AND kind='treatment' AND entity_id=%s FOR UPDATE", (tenant, run_id)).fetchone()
            if not row:
                raise RunMissing()
            version, run = row
            expected = "analysis" if not run["steps"] else "storyboard"
            if run["status"] != "running" or run.get("current_step") or step != expected:
                raise RunConflict()
            prompt_id = uuid5(run_id, step + ":prompt")
            treatment_id = uuid5(run_id, step + ":treatment")
            started_at = now()
            self._write(conn, tenant, actor, run_id, "prompt", prompt_id,
                        {"run_id": str(run_id), "version": 1, "step": step, "text": prompt,
                         "prompt_version": "1.2.0", "workflow_version": WORKFLOW_VERSION})
            self._write(conn, tenant, actor, run_id, "treatment", treatment_id,
                        {"run_id": str(run_id), "step": step, "prompt_id": str(prompt_id),
                         "status": "running", "started_at": started_at,
                         "parameters": {"max_tokens": 2048, "stream": False,
                                        "temperature": 0.1, "response_format": "json_object",
                                        "system_prompt_version": "1.2.0"}})
            run.update(current_step={"name": step, "treatment_id": str(treatment_id),
                                     "prompt_id": str(prompt_id), "started_at": started_at}, updated_at=started_at)
            self._write(conn, tenant, actor, run_id, "treatment", run_id, run, version)

    def save_step(self, tenant, actor, run_id, step, prompt, response, parsed, error_code=None):
        # One transaction covers the exact prompt/output snapshot, treatment,
        # domain objects, run transition, audit rows, and Slack outbox references.
        with self.connect() as conn:
            row = conn.execute("SELECT version,content FROM po_entity WHERE tenant_id=%s AND kind='treatment' AND entity_id=%s FOR UPDATE", (tenant, run_id)).fetchone()
            if not row:
                raise RunMissing()
            version, run = row
            if run.get("status") != "running" or step in [x["name"] for x in run["steps"]]:
                raise RunConflict()
            expected = "analysis" if not run["steps"] else "storyboard"
            if step != expected:
                raise RunConflict()
            prompt_id = uuid5(run_id, step + ":prompt")
            treatment_id = uuid5(run_id, step + ":treatment")
            result_id = uuid5(run_id, step + ":result")
            if run.get("current_step", {}).get("name") != step:
                raise RunConflict()
            treatment = {"run_id": str(run_id), "step": step, "prompt_id": str(prompt_id),
                         "result_id": str(result_id), "status": "failed" if error_code else "success",
                         "error_code": error_code, "model": response.get("model"),
                         "provider": response.get("provider"), "usage": response.get("usage"),
                         "duration_seconds": response.get("duration_seconds"),
                         "finish_reason": response.get("finish_reason"), "parameters": {"max_tokens": 2048, "stream": False,
                         "temperature": 0.1, "response_format": "json_object", "system_prompt_version": "1.2.0"},
                         "started_at": run["current_step"]["started_at"], "finished_at": now()}
            self._write(conn, tenant, actor, run_id, "treatment", treatment_id, treatment, 1)
            self._write(conn, tenant, actor, run_id, "result", result_id,
                        {"run_id": str(run_id), "type": "editorial_step_snapshot", "order": len(run["steps"]),
                         "prompt_id": str(prompt_id), "treatment_id": str(treatment_id),
                         "prompt": prompt, "prompt_version": "1.2.0", "response_metadata": {k: v for k, v in response.items() if k not in {"prompt", "response"}},
                         "raw_response": response.get("response"), "parsed": parsed, "error_code": error_code})
            run["steps"].append({"name": step, "status": treatment["status"], "treatment_id": str(treatment_id), "result_id": str(result_id)})
            if error_code:
                run.update(status="failed", error_code=error_code)
            elif step == "analysis":
                run["analysis"] = parsed
            else:
                scenario_id = uuid5(run_id, "scenario")
                scene_ids = []
                for order, scene in enumerate(parsed["scenes"], 1):
                    scene_id = uuid5(scenario_id, str(order))
                    scene_ids.append(str(scene_id))
                    self._write(conn, tenant, actor, run_id, "scene", scene_id,
                                scene | {"scenario_id": str(scenario_id), "run_id": str(run_id), "order": order,
                                         "source_treatment_id": str(treatment_id)})
                self._write(conn, tenant, actor, run_id, "scenario", scenario_id,
                            {"run_id": str(run_id), "title": parsed["title"], "synopsis": parsed["synopsis"],
                             "scene_ids": scene_ids, "source_treatment_id": str(treatment_id),
                             "requires_human_validation": True})
                run.update(status="waiting_validation", storyboard=parsed, scenario_id=str(scenario_id), scene_ids=scene_ids)
            run.pop("current_step", None)
            run["updated_at"] = now()
            self._write(conn, tenant, actor, run_id, "treatment", run_id, run, version)
            return run


    @staticmethod
    def _visual_scene(run, scene_number):
        if not run.get("storyboard") or not isinstance(scene_number, int):
            raise RunConflict()
        scene_ids = run.get("scene_ids") or []
        if not (1 <= scene_number <= len(scene_ids)):
            raise RunMissing()
        return UUID(scene_ids[scene_number - 1])

    @staticmethod
    def _visual_id(scene_id):
        return uuid5(scene_id, "private-image-v1")

    def visual_plan(self, tenant, run_id):
        """Projection for UI, no binary payload and no secret storage paths."""
        from editorial.visuals import characters, image_prompt
        with self.connect() as conn:
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s AND NOT deleted", (tenant, run_id),
            ).fetchone()
            if not row or row[0].get("type") != "editorial_run":
                raise RunMissing()
            run = row[0]
            board = run.get("storyboard")
            if not board or run.get("storyboard_stale"):
                return {"run_id": str(run_id), "characters": [], "scenes": [],
                        "approved": False}
            entries = []
            scene_ids = run.get("scene_ids") or []
            for i, scene_id in enumerate(scene_ids, 1):
                asset_id = self._visual_id(UUID(scene_id))
                record = conn.execute(
                    "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                    "AND entity_id=%s AND NOT deleted", (tenant, asset_id),
                ).fetchone()
                asset = record[0] if record and record[0].get("scenario_id") == run.get("scenario_id") else None
                generation = None
                if asset:
                    generation = {key: asset.get(key) for key in (
                        "created_at", "finished_at", "duration_seconds", "error_code",
                        "png_sha256", "byte_count", "width", "height", "provenance",
                        "outcome_uncertain", "code_version", "scenario_id")}
                    # Full character/prompt snapshots stay in the private audit record.
                    if generation["provenance"]:
                        generation["provenance"] = {
                            key: value for key, value in generation["provenance"].items()
                            if key != "character_references"}
                entries.append({"scene_number": i, "scene_id": scene_id,
                                "title": board["scenes"][i - 1]["title"],
                                "prompt": image_prompt(run, i),
                                "image_status": asset.get("status", "not_generated") if asset else "not_generated",
                                "generation": generation})
            return {"run_id": str(run_id), "characters": characters(board),
                    "scenes": entries, "approved": run["status"] == "approved"}

    def begin_image(self, tenant, actor, run_id, scene_number, prompt, expected_scene_id=None):
        """Reserve image exactly once; audit and outbox share the transaction."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s AND NOT deleted FOR UPDATE", (tenant, run_id),
            ).fetchone()
            if not row or row[0].get("type") != "editorial_run":
                raise RunMissing()
            run = row[0]
            if run.get("status") != "approved" or run.get("storyboard_stale"):
                raise RunConflict()
            scene_id = self._visual_scene(run, scene_number)
            from editorial.visuals import image_prompt, image_provenance
            if ((expected_scene_id is not None and scene_id != expected_scene_id)
                    or prompt != image_prompt(run, scene_number)):
                raise RunConflict()
            asset_id = self._visual_id(scene_id)
            existing = conn.execute(
                "SELECT 1 FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted", (tenant, asset_id),
            ).fetchone()
            if existing:
                # Manual reconciliation of failed/ambiguous images only.
                raise RunConflict()
            self._write(conn, tenant, actor, run_id, "result", asset_id,
                        {"type": "scene_image_asset", "run_id": str(run_id),
                         "scenario_id": run["scenario_id"], "scene_id": str(scene_id),
                         "scene_number": scene_number, "status": "generating",
                         "prompt": prompt, "created_at": now(),
                         "code_version": runtime_code_version(),
                         "provenance": image_provenance(run, scene_number, prompt)})
            return scene_id, asset_id

    def finish_image(self, tenant, actor, run_id, scene_id, *, width=None, height=None,
                     error_code=None, duration_seconds=None, png_sha256=None, byte_count=None):
        """Finalize exact reserved record; never overwrite an earlier asset."""
        with self.connect() as conn:
            asset_id = self._visual_id(scene_id)
            row = conn.execute(
                "SELECT version,content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted FOR UPDATE", (tenant, asset_id),
            ).fetchone()
            if not row or row[1].get("type") != "scene_image_asset" or row[1].get("run_id") != str(run_id):
                raise RunMissing()
            version, record = row
            if record["status"] != "generating":
                raise RunConflict()
            current = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s AND NOT deleted", (tenant, run_id),
            ).fetchone()
            if not current or current[0].get("scenario_id") != record["scenario_id"] or current[0].get("status") != "approved":
                raise RunConflict()
            record.update(status="failed" if error_code else "ready",
                          finished_at=now(), error_code=error_code,
                          duration_seconds=duration_seconds,
                          outcome_uncertain=error_code in {
                              "image_provider_timeout", "image_provider_response_uncertain"})
            if not error_code:
                record.update(width=width, height=height, mime_type="image/png",
                              png_sha256=png_sha256, byte_count=byte_count)
            self._write(conn, tenant, actor, run_id, "result", asset_id, record, version)
            return {"scene_number": record["scene_number"], "status": record["status"],
                    "width": record.get("width"), "height": record.get("height"),
                    "duration_seconds": duration_seconds}

    def image_audit_counts(self, tenant, run_id):
        """Read-only evidence, scoped to the current run and its current scenes."""
        run = self.get(tenant, run_id)
        with self.connect() as conn:
            counts = {}
            for scene_id in run.get("scene_ids") or []:
                asset_id = self._visual_id(UUID(scene_id))
                count = conn.execute(
                    "SELECT COUNT(*) FROM po_audit a JOIN po_outbox o USING(event_id) "
                    "WHERE a.tenant_id=%s AND a.kind='result' AND a.entity_id=%s AND a.correlation_id=%s",
                    (tenant, asset_id, run_id)).fetchone()[0]
                counts[scene_id] = count
            return counts

    def image_asset(self, tenant, run_id, scene_number):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s AND NOT deleted", (tenant, run_id)
            ).fetchone()
            if not row or row[0].get("type") != "editorial_run":
                raise RunMissing()
            run = row[0]
            if run.get("status") != "approved" or run.get("storyboard_stale"):
                raise RunMissing()
            scene_id = self._visual_scene(run, scene_number)
            asset = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted", (tenant, self._visual_id(scene_id)),
            ).fetchone()
            if not asset or asset[0].get("status") != "ready" or asset[0].get("scenario_id") != run["scenario_id"]:
                raise RunMissing()
            return scene_id

    def review(self, tenant, actor, run_id, step, decision):
        decision = ReviewDecision.model_validate(decision)
        with self.connect() as conn:
            row = conn.execute(
                "SELECT version,content FROM po_entity WHERE tenant_id=%s AND kind='treatment' AND entity_id=%s AND NOT deleted FOR UPDATE",
                (tenant, run_id)).fetchone()
            if not row or row[1].get("type") != "editorial_run":
                raise RunMissing()
            version, run = row
            if (step not in {"analysis", "storyboard"} or run["status"] not in {"waiting_validation", "changes_requested"}
                    or run.get("current_step") or len(run.get("steps", [])) != 2
                    or any(s["status"] != "success" for s in run["steps"])
                    or decision.expected_revision != run.get("review_revision", 0)):
                raise RunConflict()
            if step == "storyboard" and run.get("storyboard_stale") and decision.action == "accept":
                raise RunConflict()
            parsed = None
            if decision.action == "revise":
                parsed = validated_review_output(step, decision.revised_output, run["brief"])
            elif decision.action == "accept":
                validated_review_output(step, run.get(step), run["brief"])
            revision = run.get("review_revision", 0) + 1
            review_id = uuid5(run_id, "human-review:" + str(revision))
            reviews = run.setdefault("reviews", {})
            if parsed is not None:
                run[step] = parsed
                if step == "analysis":
                    run["storyboard_stale"] = True
                    if "storyboard" in reviews:
                        reviews["storyboard"]["valid"] = False
                else:
                    run["storyboard_stale"] = False
                    scenario_id = uuid5(review_id, "scenario")
                    scene_ids = []
                    for order, scene in enumerate(parsed["scenes"], 1):
                        scene_id = uuid5(scenario_id, str(order))
                        scene_ids.append(str(scene_id))
                        self._write(conn, tenant, actor, run_id, "scene", scene_id,
                                    scene | {"scenario_id": str(scenario_id), "run_id": str(run_id),
                                             "order": order, "source_review_id": str(review_id)})
                    self._write(conn, tenant, actor, run_id, "scenario", scenario_id,
                                {"run_id": str(run_id), "title": parsed["title"], "synopsis": parsed["synopsis"],
                                 "scene_ids": scene_ids, "source_review_id": str(review_id),
                                 "requires_human_validation": True})
                    run.update(scenario_id=str(scenario_id), scene_ids=scene_ids)
            reviews[step] = {"action": decision.action, "revision": revision, "valid": True,
                             "review_id": str(review_id)}
            approved = not run.get("storyboard_stale") and all(
                reviews.get(s, {}).get("action") == "accept" and reviews[s].get("valid")
                for s in ("analysis", "storyboard"))
            pending_changes = run.get("storyboard_stale") or any(
                r["action"] in {"reject", "revise"} for r in reviews.values())
            run.update(review_revision=revision, updated_at=now(), requires_human_validation=not approved,
                       status="approved" if approved else ("changes_requested" if pending_changes else "waiting_validation"))
            if approved:
                for approved_step in ("analysis", "storyboard"):
                    validated_review_output(approved_step, run.get(approved_step), run["brief"])
                scenario = conn.execute(
                    "SELECT version,content FROM po_entity WHERE tenant_id=%s AND kind='scenario' AND entity_id=%s AND NOT deleted FOR UPDATE",
                    (tenant, UUID(run["scenario_id"]))).fetchone()
                if not scenario:
                    raise RunConflict()
                scenario_version, content = scenario
                content.update(requires_human_validation=False, approved_by=str(actor), approved_at=run["updated_at"])
                self._write(conn, tenant, actor, run_id, "scenario", UUID(run["scenario_id"]), content, scenario_version)
            self._write(conn, tenant, actor, run_id, "result", review_id,
                        {"type": "editorial_review", "run_id": str(run_id), "step": step,
                         "revision": revision, "action": decision.action, "comment": decision.comment,
                         "actor_id": str(actor), "created_at": run["updated_at"],
                         "effective_output": run[step], "source_result_id": next(s["result_id"] for s in run["steps"] if s["name"] == step),
                         "scenario_id": run.get("scenario_id") if step == "storyboard" else None})
            self._write(conn, tenant, actor, run_id, "treatment", run_id, run, version)
            return run

    def review_history(self, tenant, run_id, limit=20, before_revision=None):
        self.get(tenant, run_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' AND content->>'run_id'=%s "
                "AND content->>'type'='editorial_review' AND NOT deleted "
                "AND (%s::integer IS NULL OR (content->>'revision')::integer < %s) "
                "ORDER BY (content->>'revision')::integer DESC LIMIT %s",
                (tenant, str(run_id), before_revision, before_revision, limit+1)).fetchall()
            return [row[0] for row in rows]
