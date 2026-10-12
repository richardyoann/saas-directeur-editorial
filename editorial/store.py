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

WORKFLOW_VERSION = "editorial-v1.1"


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

    def start(self, tenant, actor, key, brief):
        run_id = uuid5(tenant, "editorial-run:" + str(key))
        digest = fingerprint(brief, actor)
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,2))", (str(run_id),))
            row = conn.execute("SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' AND entity_id=%s AND NOT deleted", (tenant, run_id)).fetchone()
            if row:
                if row[0].get("request_hash") != digest:
                    raise RunConflict()
                return row[0], False
            run = {"id": str(run_id), "type": "editorial_run", "workflow_version": WORKFLOW_VERSION,
                   "request_hash": digest, "brief": brief, "status": "running", "steps": [],
                   "code_version": runtime_code_version(),
                   "created_at": now(), "updated_at": now(), "requires_human_validation": True}
            self._write(conn, tenant, actor, run_id, "treatment", run_id, run)
            return run, True

    def get(self, tenant, run_id):
        with self.connect() as conn:
            row = conn.execute("SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' AND entity_id=%s AND NOT deleted", (tenant, run_id)).fetchone()
            if not row or row[0].get("type") != "editorial_run":
                raise RunMissing()
            return row[0]

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
                         "prompt_version": "1.1.0", "workflow_version": WORKFLOW_VERSION})
            self._write(conn, tenant, actor, run_id, "treatment", treatment_id,
                        {"run_id": str(run_id), "step": step, "prompt_id": str(prompt_id),
                         "status": "running", "started_at": started_at,
                         "parameters": {"max_tokens": 2048, "stream": False,
                                        "temperature": 0.1, "response_format": "json_object",
                                        "system_prompt_version": "1.1.0"}})
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
                         "temperature": 0.1, "response_format": "json_object", "system_prompt_version": "1.1.0"},
                         "started_at": run["current_step"]["started_at"], "finished_at": now()}
            self._write(conn, tenant, actor, run_id, "treatment", treatment_id, treatment, 1)
            self._write(conn, tenant, actor, run_id, "result", result_id,
                        {"run_id": str(run_id), "type": "editorial_step_snapshot", "order": len(run["steps"]),
                         "prompt_id": str(prompt_id), "treatment_id": str(treatment_id),
                         "prompt": prompt, "prompt_version": "1.1.0", "response_metadata": {k: v for k, v in response.items() if k not in {"prompt", "response"}},
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
