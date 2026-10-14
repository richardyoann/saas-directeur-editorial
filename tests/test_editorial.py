import copy
import json
import os
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4, uuid5

import httpx
from apps.api.main import app, get_llm_client
from apps.api.llama_provider import generation_gate
from editorial.api import Identity, get_identity, get_store
from editorial.models import Brief
from editorial.service import parse_output
from editorial.store import RunConflict, RunMissing, fingerprint


def outputs():
    analysis = {"angle": "Une légende maritime", "message": "Le rapport à la mer", "historical_checks": ["Vérifier les variantes de la légende"]}
    scene = {"title": "Le rivage", "duration_seconds": 20, "narration": "Une légende raconte…",
             "visual_description": "Un rivage breton", "characters": ["Un marin"], "landscape": "Côte bretonne",
             "colors": ["bleu"], "shot": "Plan large", "emotion": "Mystère", "sound": "Vagues",
             "image_prompt": "Un rivage sous la brume"}
    storyboard = {"title": "La mer", "synopsis": "Récit légendaire", "scenes": [copy.deepcopy(scene) for _ in range(3)]}
    return analysis, storyboard


class MemoryStore:
    """Service fixture only; it is never used by the application runtime."""
    def __init__(self):
        self.runs = {}
        self.snapshots = {}
        self.mutation_actors = []

    def start(self, tenant, actor, key, brief):
        run_id = uuid5(tenant, "editorial-run:" + str(key))
        digest = fingerprint(brief, actor)
        if run_id in self.runs:
            run = self.runs[run_id]
            if run["request_hash"] != digest:
                raise RunConflict()
            return copy.deepcopy(run), False
        run = {"id": str(run_id), "status": "running", "steps": [], "brief": brief,
               "request_hash": digest, "requires_human_validation": True,
               "run_owner_actor": str(actor)}
        self.runs[run_id] = run
        return copy.deepcopy(run), True

    def enqueue(self, tenant, actor, key, brief):
        run, created = self.start(tenant, actor, key, brief)
        if created:
            self.runs[UUID(run["id"])]["status"] = "queued"
            run["status"] = "queued"
        return run, created

    def claim_queued(self, tenant, actor):
        for run in self.runs.values():
            if run["status"] == "queued":
                run["status"] = "running"
                return copy.deepcopy(run)
        return None

    def begin_step(self, tenant, actor, run_id, step, prompt):
        self.mutation_actors.append(actor)
        self.runs[run_id]["current_step"] = {"name": step}

    def save_step(self, tenant, actor, run_id, step, prompt, response, parsed, error):
        self.mutation_actors.append(actor)
        run = self.runs[run_id]
        run["steps"].append({"name": step, "status": "failed" if error else "success"})
        self.snapshots.setdefault(run_id, []).append({"prompt": prompt, "raw_response": response.get("response"), "error_code": error})
        if error:
            run.update(status="failed", error_code=error)
        elif step == "analysis":
            run["analysis"] = parsed
        else:
            run.update(status="waiting_validation", storyboard=parsed)
        run.pop("current_step", None)
        return copy.deepcopy(run)

    def get(self, tenant, run_id):
        if run_id not in self.runs:
            raise RunMissing()
        return copy.deepcopy(self.runs[run_id])

    def history(self, tenant, run_id):
        self.get(tenant, run_id)
        return self.snapshots[run_id]


class EditorialApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"LLM_BASE_URL": "http://model.test"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(app.dependency_overrides.clear)
        self.store = MemoryStore()
        self.tenant, self.actor, self.key = uuid4(), uuid4(), uuid4()
        app.dependency_overrides[get_identity] = lambda: Identity(self.tenant, self.actor)
        app.dependency_overrides[get_store] = lambda: self.store
        self.calls = []
        self.responses = list(outputs())
        self.reason = "stop"

        def handler(request):
            self.calls.append(request)
            value = self.responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return httpx.Response(200, json={"model": "Qwen-test", "choices": [{
                "message": {"content": value if isinstance(value, str) else json.dumps(value)},
                "finish_reason": self.reason}], "usage": {"total_tokens": 50}})

        async def client():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                yield c
        app.dependency_overrides[get_llm_client] = client
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test")
        self.addAsyncCleanup(self.client.aclose)

    async def post(self, **brief):
        return await self.client.post("/editorial/runs", headers={"Idempotency-Key": str(self.key)}, json={"topic": "La ville d'Ys", **brief})

    async def test_async_queue_202_no_llm_in_request_worker_completes(self):
        from workers.editorial_worker import once

        with patch.dict(os.environ, {"EDITORIAL_ASYNC_ENABLED": "true"}):
            first = await self.post()
            self.assertEqual(first.status_code, 202)
            self.assertEqual(first.json()["status"], "queued")
            self.assertEqual((await self.post()).status_code, 202)
            self.assertEqual(self.calls, [])
            def handler(request):
                self.calls.append(request)
                answer = self.responses.pop(0)
                return httpx.Response(200, json={"model": "Qwen-test", "choices": [{
                    "message": {"content": json.dumps(answer)}, "finish_reason": "stop"
                }], "usage": {"total_tokens": 50}})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as llm:
                worker_actor = uuid4()
                self.assertNotEqual(worker_actor, self.actor)
                self.assertTrue(await once(self.store, self.tenant, worker_actor, llm, "http://model.test"))
                self.assertFalse(await once(self.store, self.tenant, worker_actor, llm, "http://model.test"))
            self.assertEqual(len(self.calls), 2)
            self.assertEqual(set(self.store.mutation_actors), {self.actor})
            self.assertEqual(self.store.get(self.tenant, UUID(first.json()["id"]))["status"], "waiting_validation")
            replay = await self.post()
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(len(self.calls), 2)
            self.assertEqual((await self.post(topic="Autre sujet")).status_code, 409)

    async def test_sync_mode_default_unchanged_when_flag_disabled(self):
        with patch.dict(os.environ, {"EDITORIAL_ASYNC_ENABLED": "false"}):
            self.assertEqual((await self.post()).status_code, 201)
            self.assertEqual(len(self.calls), 2)

    async def test_complete_workflow_replay_and_history(self):
        response = await self.post()
        self.assertEqual(response.status_code, 201)
        run = response.json()
        self.assertEqual(run["status"], "waiting_validation")
        self.assertTrue(run["requires_human_validation"])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(len(run["storyboard"]["scenes"]), 3)
        self.assertEqual((await self.post()).status_code, 200)
        self.assertEqual(len(self.calls), 2)
        history = await self.client.get(f"/editorial/runs/{run['id']}/history")
        self.assertEqual(len(history.json()["steps"]), 2)
        self.assertIn("La ville d'Ys", history.json()["steps"][0]["prompt"])
        self.assertEqual((await self.client.get(f"/editorial/runs/{run['id']}")).json()["status"], "waiting_validation")
        self.assertEqual((await self.post(topic="Autre sujet")).status_code, 409)

    async def test_invalid_or_truncated_output_stops_and_is_saved(self):
        for reason, output, code in (("stop", "pas du JSON", "invalid_structured_output"),
                                     ("length", json.dumps(outputs()[0]), "output_incomplete"),
                                     (None, json.dumps(outputs()[0]), "output_incomplete"),
                                     ("content_filter", json.dumps(outputs()[0]), "output_incomplete")):
            self.key = uuid4()
            self.responses = [output]
            self.reason = reason
            before = len(self.calls)
            response = await self.post()
            self.assertEqual(response.status_code, 422)
            run = response.json()
            self.assertEqual(run["error_code"], code)
            self.assertEqual(len(self.calls), before + 1)
            self.assertEqual(self.store.snapshots[UUID(run["id"])][0]["raw_response"], output)
            self.assertEqual((await self.post()).status_code, 422)
            self.assertEqual(len(self.calls), before + 1)

    async def test_upstream_timeout_is_recorded_without_raw_error(self):
        self.responses = [httpx.ReadTimeout("secret upstream address")]
        response = await self.post()
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["error_code"], "provider_timeout")
        self.assertNotIn("secret", response.text)
        self.assertEqual(len(self.calls), 1)

    async def test_input_validation_missing_key_and_unknown_run(self):
        for body in ({"topic": " "}, {"topic": "Ys", "tenant_id": str(uuid4())},
                     {"topic": "Ys", "scene_count": 7}, {"topic": "Ys", "duration_seconds": True}):
            r = await self.client.post("/editorial/runs", headers={"Idempotency-Key": str(self.key)}, json=body)
            self.assertEqual(r.status_code, 422)
        self.assertEqual((await self.client.post("/editorial/runs", json={"topic": "Ys"})).status_code, 422)
        self.assertEqual((await self.client.get(f"/editorial/runs/{uuid4()}")).status_code, 404)
        self.assertEqual(self.calls, [])

    async def test_capacity_rejection_does_not_persist_half_started_run(self):
        self.assertTrue(generation_gate.acquire(blocking=False))
        self.assertTrue(generation_gate.acquire(blocking=False))
        try:
            response = await self.post()
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers["Retry-After"], "30")
            self.assertEqual(self.store.runs, {})
            self.assertEqual(self.calls, [])
        finally:
            generation_gate.release()
            generation_gate.release()
        response = await self.post()
        self.assertEqual(response.status_code, 201)

    async def test_authentication_fails_closed(self):
        app.dependency_overrides.pop(get_identity)
        config = {"EDITORIAL_API_TOKEN": "x" * 32, "EDITORIAL_TENANT_ID": str(self.tenant), "EDITORIAL_ACTOR_ID": str(self.actor)}
        with patch.dict(os.environ, config):
            self.assertEqual((await self.post()).status_code, 401)
            response = await self.client.post("/editorial/runs", headers={"Authorization": "Bearer " + "x"*32, "Idempotency-Key": str(self.key)}, json={"topic": "Ys"})
            self.assertEqual(response.status_code, 201)
        with patch.dict(os.environ, config | {"EDITORIAL_API_TOKEN": "short"}):
            self.assertEqual((await self.post()).status_code, 503)


class OutputTests(unittest.TestCase):
    def test_storyboard_duration_count_and_duplicate_json(self):
        brief = Brief(topic="Ys")
        _, storyboard = outputs()
        self.assertEqual(len(parse_output(json.dumps(storyboard), "storyboard", brief)["scenes"]), 3)
        for changed in (storyboard | {"scenes": storyboard["scenes"][:2]},
                        storyboard | {"scenes": [x | {"duration_seconds": 21} for x in storyboard["scenes"]]}):
            with self.assertRaises(ValueError):
                parse_output(json.dumps(changed), "storyboard", brief)
        with self.assertRaises(ValueError):
            parse_output('{"angle":"A","angle":"B","message":"C","historical_checks":[]}', "analysis", brief)
