"""End-to-end Studio facade for an explicit first production role (fake DB/Qwen)."""
import json
import os
import unittest
from unittest.mock import patch
from pathlib import Path
from uuid import uuid4

import httpx

from apps.api.main import app, get_llm_client
from apps.api.studio import sessions, failures
from editorial.api import get_store
from editorial.store import RunConflict, RunMissing
from production.crew import ROLES, source_snapshot
from test_production_crew import approved_run


class FakeProduction:
    def __init__(self):
        self.state = None
        self.tenant = None
        self.calls = 0

    def start(self, tenant, actor, run_id):
        self.tenant = tenant
        if self.state:
            return dict(self.state), False
        self.state = {
            "id": str(uuid4()), "run_id": str(run_id), "source": source_snapshot(approved_run()),
            "source_revision": 2, "phase": "ready", "next_roles": list(ROLES),
            "current_role": None, "revision": 0, "outputs": {}, "feedback": [],
            "cycle": 0, "quality": None, "critique": None,
        }
        return dict(self.state), True

    def get(self, tenant, run_id):
        self.tenant = tenant
        if not self.state:
            raise RunMissing()
        return dict(self.state)

    def claim(self, tenant, actor, run_id, expected_revision):
        if not self.state or self.state["phase"] != "ready" or expected_revision != self.state["revision"]:
            raise RunConflict()
        self.state["phase"] = "running"
        self.state["current_role"] = self.state["next_roles"][0]
        self.state["revision"] += 1
        return dict(self.state)

    def finish(self, tenant, actor, run_id, claimed_revision, role, output=None, error=None):
        if not self.state or self.state["revision"] != claimed_revision:
            raise RunConflict()
        self.state["phase"] = "blocked_failure" if error else "ready"
        self.state["outputs"][role] = output
        self.state["next_roles"].pop(0)
        self.state["current_role"] = None
        self.state["revision"] += 1
        return dict(self.state)


class ProductionStudioDefaultsTests(unittest.TestCase):
    def test_story_form_defaults_match_seventy_five_second_production(self):
        html = (Path(__file__).resolve().parents[1] / "apps/web/studio.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="duration" type="number" min="15" max="180" value="75"', html)
        self.assertIn('id="scenes" type="number" min="1" max="6" value="5"', html)


class ProductionStudioJourneyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sessions.clear()
        failures.clear()
        self.tenant, self.actor, self.run_id = uuid4(), uuid4(), uuid4()
        self.env = patch.dict(os.environ, {
            "EDITORIAL_WEB_PASSWORD": "w" * 48, "EDITORIAL_API_TOKEN": "t" * 48,
            "EDITORIAL_TENANT_ID": str(self.tenant), "EDITORIAL_ACTOR_ID": str(self.actor),
            "LLM_BASE_URL": "http://model.test"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.production = FakeProduction()
        self.production_override = patch("production.api.ProductionStore",
                                         side_effect=lambda store: self.production)
        self.production_override.start()
        self.addCleanup(self.production_override.stop)
        app.dependency_overrides[get_store] = lambda: object()
        self.addCleanup(app.dependency_overrides.clear)
        self.upstream_calls = []

        def model(request):
            self.upstream_calls.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                "summary": "Une histoire qui conserve son rythme et sa continuité.",
                "directions": ["Établir une accroche forte puis conclure."],
                "constraints_checked": ["Durée approuvée de 75 secondes inchangée."],
                "handoff": "Transmettre les intentions au directeur artistique.",
            })}, "finish_reason": "stop"}]})

        async def fake_llm():
            async with httpx.AsyncClient(transport=httpx.MockTransport(model)) as client:
                yield client

        app.dependency_overrides[get_llm_client] = fake_llm
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                        base_url="http://localhost")
        self.addAsyncCleanup(self.client.aclose)
        self.origin = {"Origin": "http://localhost"}

    async def test_auth_csrf_start_one_role_and_no_automatic_replay(self):
        base = f"/studio/api/runs/{self.run_id}/production"
        self.assertEqual((await self.client.get(base)).status_code, 401)
        response = await self.client.post("/studio/session", headers=self.origin,
                                          json={"password": "w" * 48})
        self.assertEqual(response.status_code, 200)
        headers = self.origin | {"X-CSRF-Token": response.json()["csrf"]}
        self.assertEqual((await self.client.get(base)).status_code, 404)
        self.assertEqual((await self.client.post(base, headers=self.origin)).status_code, 403)
        response = await self.client.post(base, headers=headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["next_roles"][0], "screenwriter")
        self.assertEqual(self.upstream_calls, [])
        result = await self.client.post(base + "/advance", headers=headers,
                                        json={"expected_revision": 0})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["next_roles"][0], "art_director")
        self.assertEqual(len(self.upstream_calls), 1)
        self.assertEqual(self.production.tenant, self.tenant)
        duplicate = await self.client.post(base + "/advance", headers=headers,
                                           json={"expected_revision": 0})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(len(self.upstream_calls), 1)


if __name__ == "__main__":
    unittest.main()
