import copy
import json
import os
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4, uuid5

import httpx
from apps.api.main import app, get_llm_client
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

    def start(self, tenant, actor, key, brief):
        run_id = uuid5(tenant, "editorial-run:" + str(key))
        digest = fingerprint(brief, actor)
        if run_id in self.runs:
            run = self.runs[run_id]
            if run["request_hash"] != digest:
                raise RunConflict()
            return copy.deepcopy(run), False
        run = {"id": str(run_id), "status": "running", "steps": [], "brief": brief,
               "request_hash": digest, "requires_human_validation": True}
        self.runs[run_id] = run
        return copy.deepcopy(run), True

    def begin_step(self, tenant, actor, run_id, step, prompt):
        self.runs[run_id]["current_step"] = {"name": step}

    def save_step(self, tenant, actor, run_id, step, prompt, response, parsed, error):
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
