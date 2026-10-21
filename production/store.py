"""Durable multi-role planning; existing po_entity + audit/outbox, no migration.

Every model request is explicitly claimed once before network I/O. A crash or
timeout is NEVER replayed automatically: operators inspect a blocked stage.
"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID, uuid5

from editorial.store import RunConflict, RunMissing, now
from production.crew import (ROLES, SPECIALISTS, SpecialistOutput, CriticOutput,
                             source_snapshot, quality_gate, role_prompt)

MAX_CORRECTIONS = 2


def source_digest(source):
    raw = json.dumps(source, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ProductionStore:
    def __init__(self, editorial_store):
        self.store = editorial_store

    @staticmethod
    def session_id(run_id, revision):
        return uuid5(run_id, "production-crew-v1:" + str(revision))

    @staticmethod
    def _run(conn, tenant, run_id):
        row = conn.execute(
            "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
            "AND entity_id=%s AND NOT deleted FOR UPDATE", (tenant, run_id)
        ).fetchone()
        if not row or row[0].get("type") != "editorial_run":
            raise RunMissing()
        return row[0]

    @staticmethod
    def _session(conn, tenant, session_id):
        row = conn.execute(
            "SELECT version, content FROM po_entity WHERE tenant_id=%s AND kind='result' "
            "AND entity_id=%s AND NOT deleted FOR UPDATE", (tenant, session_id)
        ).fetchone()
        if not row or row[1].get("type") != "production_crew_session":
            raise RunMissing()
        return row

    def _save(self, conn, tenant, actor, run_id, session_id, state, version):
        self.store._write(conn, tenant, actor, run_id, "result", session_id, state, version)

    def start(self, tenant, actor, run_id):
        with self.store.connect() as conn:
            run = self._run(conn, tenant, run_id)
            source = source_snapshot(run)
            identifier = self.session_id(run_id, source["review_revision"])
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted FOR UPDATE", (tenant, identifier)
            ).fetchone()
            if row:
                return row[0], False
            state = {
                "type": "production_crew_session", "id": str(identifier),
                "run_id": str(run_id), "source_revision": source["review_revision"],
                "source_hash": source_digest(source), "source": source,
                "phase": "ready", "next_roles": list(ROLES),
                "outputs": {}, "events": [], "critique": None, "quality": None,
                "feedback": [], "cycle": 0, "revision": 0,
                "current_role": None, "started_at": None,
                "created_at": now(), "updated_at": now(),
                "human_review_required": True,
            }
            self._save(conn, tenant, actor, run_id, identifier, state, 0)
            return state, True

    def get(self, tenant, run_id):
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='treatment' "
                "AND entity_id=%s AND NOT deleted", (tenant, run_id)
            ).fetchone()
            if not row or row[0].get("type") != "editorial_run":
                raise RunMissing()
            run = row[0]
            revision = run.get("review_revision")
            if type(revision) is not int:
                raise RunMissing()
            identifier = self.session_id(run_id, revision)
            entry = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted", (tenant, identifier)
            ).fetchone()
            if not entry:
                raise RunMissing()
            state = entry[0]
            # Historical files remain readable even after an editorial revision.
            try:
                actual = source_snapshot(run)
                state["stale"] = source_digest(actual) != state["source_hash"]
            except (ValueError, TypeError, KeyError):
                state["stale"] = True
            return state

    def _locked(self, conn, tenant, run_id):
        run = self._run(conn, tenant, run_id)
        source = source_snapshot(run)
        identifier = self.session_id(run_id, source["review_revision"])
        version, state = self._session(conn, tenant, identifier)
        if state["source_hash"] != source_digest(source):
            raise RunConflict()
        return identifier, version, state

    def claim(self, tenant, actor, run_id, expected_revision):
        with self.store.connect() as conn:
            identifier, version, state = self._locked(conn, tenant, run_id)
            if (state["revision"] != expected_revision or state["phase"] != "ready"
                    or state["current_role"] or not state["next_roles"]):
                raise RunConflict()
            role = state["next_roles"][0]
            prompt_id = uuid5(identifier, "prompt:" + str(state["cycle"]) + ":" + role)
            self.store._write(conn, tenant, actor, run_id, "prompt", prompt_id,
                              {"type": "production_role_prompt", "session_id": str(identifier),
                               "run_id": str(run_id), "cycle": state["cycle"],
                               "role": role, "version": "production-crew-v1",
                               "text": role_prompt(role, state["source"],
                                                   state["outputs"], feedback=state["feedback"]),
                               "created_at": now()})
            state.update(phase="running", current_role=role,
                         started_at=now(), updated_at=now(), revision=expected_revision + 1)
            self._save(conn, tenant, actor, run_id, identifier, state, version)
            return state

    def finish(self, tenant, actor, run_id, claimed_revision, role, output=None, error=None):
        with self.store.connect() as conn:
            identifier, version, state = self._locked(conn, tenant, run_id)
            if (state["phase"] != "running" or state["revision"] != claimed_revision
                    or state["current_role"] != role or state["next_roles"][0] != role):
                raise RunConflict()
            if error is None:
                validated = CriticOutput if role == "critic" else SpecialistOutput
                output = validated.model_validate(output).model_dump()
            record = {"type": "production_crew_output", "run_id": str(run_id),
                      "session_id": str(identifier), "cycle": state["cycle"],
                      "role": role, "status": "failed" if error else "completed",
                      "output": output if not error else None,
                      "error_code": error, "created_at": now()}
            record_id = uuid5(identifier, "cycle:" + str(state["cycle"]) + ":" + role)
            self.store._write(conn, tenant, actor, run_id, "result", record_id, record)
            state["events"].append({"cycle": state["cycle"], "role": role,
                                    "status": record["status"], "created_at": record["created_at"]})
            state.update(current_role=None, started_at=None, updated_at=now(),
                         revision=state["revision"] + 1)
            if error:
                state["phase"] = "blocked_failure"
                state["error_code"] = error
            else:
                state["outputs"][role] = output
                state["next_roles"].pop(0)
                if role == "critic":
                    state["critique"] = output
                    state["quality"] = quality_gate(output)
                    if state["quality"]["passed"]:
                        state["phase"] = "ready_for_human_review"
                    else:
                        targets = output.get("target_roles", [])
                        state["phase"] = ("changes_requested" if targets and state["cycle"] < MAX_CORRECTIONS
                                          else "blocked_quality")
                else:
                    state["phase"] = "ready"
            self._save(conn, tenant, actor, run_id, identifier, state, version)
            return state

    def request_correction(self, tenant, actor, run_id, expected_revision, target_role):
        with self.store.connect() as conn:
            identifier, version, state = self._locked(conn, tenant, run_id)
            targets = (state.get("critique") or {}).get("target_roles") or []
            if (state["revision"] != expected_revision or state["phase"] != "changes_requested"
                    or state["cycle"] >= MAX_CORRECTIONS or target_role not in targets
                    or target_role not in SPECIALISTS):
                raise RunConflict()
            index = ROLES.index(target_role)
            feedback = state["critique"]["observations"] + state["critique"]["blocking_issues"]
            for role in ROLES[index:]:
                state["outputs"].pop(role, None)
            state.update(cycle=state["cycle"] + 1, phase="ready",
                         next_roles=list(ROLES[index:]),
                         critique=None, quality=None, feedback=feedback,
                         revision=state["revision"] + 1, updated_at=now())
            self._save(conn, tenant, actor, run_id, identifier, state, version)
            return state

    def reconcile(self, tenant, actor, run_id, expected_revision):
        """Manual, read-and-mark; never replay an uncertain LLM call."""
        with self.store.connect() as conn:
            identifier, version, state = self._locked(conn, tenant, run_id)
            if state["phase"] != "running" or state["revision"] != expected_revision:
                raise RunConflict()
            try:
                since = datetime.fromisoformat(state["started_at"])
                age = (datetime.now(timezone.utc) - since).total_seconds()
            except (ValueError, TypeError):
                raise RunConflict() from None
            if age < 600:
                raise RunConflict()
            state.update(phase="blocked_failure", error_code="interrupted_uncertain",
                         current_role=None, started_at=None, revision=state["revision"] + 1,
                         updated_at=now())
            self._save(conn, tenant, actor, run_id, identifier, state, version)
            return state

    def history(self, tenant, run_id):
        state = self.get(tenant, run_id)
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND NOT deleted AND content->>'type'='production_crew_output' "
                "AND content->>'session_id'=%s "
                "ORDER BY (content->>'cycle')::integer, content->>'created_at'",
                (tenant, state["id"]),
            ).fetchall()
            prompts = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='prompt' "
                "AND NOT deleted AND content->>'type'='production_role_prompt' "
                "AND content->>'session_id'=%s "
                "ORDER BY (content->>'cycle')::integer, content->>'created_at'",
                (tenant, state["id"]),
            ).fetchall()
            texts = {(row[0]["cycle"], row[0]["role"]): row[0]["text"]
                     for row in prompts}
            outputs = [row[0] for row in rows]
            for item in outputs:
                item["prompt"] = texts.get((item["cycle"], item["role"]))
            return {"session_id": state["id"], "outputs": outputs}
