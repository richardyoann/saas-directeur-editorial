"""Production-crew contract and API tests, no real model or user data."""
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from apps.api.main import app
from editorial.models import Brief
from production.crew import (ROLES, MAX_SCORES, CriticOutput, source_snapshot,
                             quality_gate, execute_role, role_prompt)


def approved_run():
    scene = {
        "title": "Le phare", "duration_seconds": 15,
        "narration": "Une voix raconte la légende de la mer.",
        "visual_description": "Un phare sur une falaise", "characters": ["Gardienne"],
        "landscape": "Côte bretonne", "colors": ["vert", "gris"],
        "shot": "Plan large", "emotion": "Mystère", "sound": "Vagues",
        "image_prompt": "Phare dans la brume",
    }
    return {
        "type": "editorial_run", "status": "approved", "storyboard_stale": False,
        "review_revision": 2,
        "brief": Brief(topic="Le phare fictif", scene_count=5,
                       duration_seconds=75, genre="fiction").model_dump(),
        "storyboard": {"title": "Le phare perdu",
                       "synopsis": "Une légende imaginée", "scenes": [dict(scene) for _ in range(5)]},
    }


def perfect_critic():
    return {**MAX_SCORES, "observations": ["Plan cohérent mais revoir la lumière."],
            "blocking_issues": [], "target_roles": []}


class CrewContractTests(unittest.TestCase):
    def test_approved_and_exact_75_seconds_gate(self):
        run = approved_run()
        snapshot = source_snapshot(run)
        self.assertEqual(snapshot["brief"]["duration_seconds"], 75)
        self.assertEqual(sum(s["duration_seconds"] for s in snapshot["storyboard"]["scenes"]), 75)
        for key, value in (("status", "waiting_validation"),
                           ("storyboard_stale", True),
                           ("review_revision", None)):
            invalid = dict(run, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                source_snapshot(invalid)
        invalid = dict(run, brief=dict(run["brief"], duration_seconds=60))
        with self.assertRaises(ValueError):
            source_snapshot(invalid)
        self.assertEqual(ROLES[-1], "critic")

    def test_score_cannot_override_bad_criterion_or_blocking_issues(self):
        report = perfect_critic()
        self.assertTrue(quality_gate(report)["passed"])
        report["narrative"] = 15
        self.assertFalse(quality_gate(report)["passed"])
        report = perfect_critic()
        report["blocking_issues"] = ["Rupture de continuité au milieu du récit."]
        report["target_roles"] = ["art_director"]
        self.assertFalse(quality_gate(report)["passed"])
        self.assertEqual(quality_gate(report)["scope"], "text_preproduction_only")
        with self.assertRaises(ValueError):
            CriticOutput.model_validate(dict(perfect_critic(), narrative=21))

    def test_prompt_transfers_data_as_untrusted_content(self):
        source = source_snapshot(approved_run())
        data = json.loads(role_prompt("critic", source, {"screenwriter": {"summary": "test"}},
                                      feedback=["Une incohérence apparaît"]))
        self.assertEqual(data["role"], "critic")
        self.assertEqual(data["locked_approved_source"]["brief"]["duration_seconds"], 75)
        self.assertIn("screenwriter", data["prior_specialist_work"])
        with self.assertRaises(ValueError):
            role_prompt("unknown", source, {})


class CrewProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_role_sends_strict_schema_and_no_code_exec_tools(self):
        requests = []
        artifact = {
            "summary": "Un scénario cinématographique structuré avec une fin marquante.",
            "directions": ["Conserver la narration sur 75 secondes."],
            "constraints_checked": ["Les cinq scènes couvrent 75 secondes."],
            "handoff": "Passer la bible au directeur artistique.",
        }
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(artifact)},
                            "finish_reason": "stop"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            got = await execute_role(client, "http://llm.test", "screenwriter",
                                     source_snapshot(approved_run()), {})
        self.assertEqual(got, artifact)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["temperature"], 0.1)
        self.assertEqual(requests[0]["response_format"]["type"], "json_object")
        self.assertNotIn("tools", requests[0])
        self.assertEqual(requests[0]["messages"][0]["role"], "system")

    async def test_critic_low_score_must_include_actionable_owner(self):
        report = dict(perfect_critic(), narrative=14)
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps(report)},
                             "finish_reason": "stop"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(ValueError):
                await execute_role(client, "http://llm.test", "critic",
                                   source_snapshot(approved_run()), {})
        self.assertEqual(len(calls), 1)

    async def test_invalid_or_truncated_response_is_not_retried(self):
        source = source_snapshot(approved_run())
        for output, reason in (("{}", "stop"), ("{}", "length"),
                               ('{"summary":"x","summary":"y"}', "stop")):
            count = []
            def handler(request):
                count.append(request)
                return httpx.Response(200, json={"choices": [{"message": {"content": output},
                                    "finish_reason": reason}]})
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                with self.subTest(output=output, reason=reason):
                    with self.assertRaises(ValueError):
                        await execute_role(client, "http://llm.test", "screenwriter", source, {})
                self.assertEqual(len(count), 1)


class CrewAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tenant, self.actor, self.run_id = uuid4(), uuid4(), uuid4()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                        base_url="http://localhost")
        self.addAsyncCleanup(self.client.aclose)

    async def test_private_agent_routes_refuse_anonymous_request(self):
        url = f"/editorial/runs/{self.run_id}/production"
        env = {"EDITORIAL_TENANT_ID": str(self.tenant),
               "EDITORIAL_ACTOR_ID": str(self.actor), "EDITORIAL_API_TOKEN": "x" * 48}
        with patch.dict(os.environ, env):
            for verb, path in (("GET", url), ("POST", url), ("POST", url + "/advance"),
                               ("POST", url + "/revise"), ("GET", url + "/history")):
                reply = await self.client.request(verb, path, json={"expected_revision": 0}
                                                  if verb == "POST" and path != url else None)
                self.assertEqual(reply.status_code, 401)

    async def test_studio_facade_requires_session_and_csrf(self):
        run = str(self.run_id)
        base = f"/studio/api/runs/{run}/production"
        self.assertEqual((await self.client.get(base)).status_code, 401)
        self.assertEqual((await self.client.post(base)).status_code, 403)
        self.assertEqual((await self.client.post(base + "/advance",
            json={"expected_revision": 0})).status_code, 403)


if __name__ == "__main__":
    unittest.main()
