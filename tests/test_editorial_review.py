import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import psycopg
from apps.api.main import app
from editorial.api import get_store
from editorial.models import Brief, ReviewDecision
from editorial.store import PostgresStore
from test_editorial import outputs


class ReviewSizeTests(unittest.TestCase):
    def test_large_revised_output_rejected_even_without_studio(self):
        from pydantic import ValidationError
        payload = {"action": "revise", "expected_revision": 0, "comment": "Correction",
                   "revised_output": {"message": "é" * 40000}}
        with self.assertRaises(ValidationError):
            ReviewDecision.model_validate(payload)
        self.assertEqual(
            ReviewDecision.model_validate(
                {"action": "revise", "expected_revision": 0, "comment": "Correction",
                 "revised_output": {"angle": "Mer"}}).revised_output,
            {"angle": "Mer"},
        )


@unittest.skipUnless(os.getenv("PO_TEST_DATABASE_URL"), "dedicated PostgreSQL required")
class HumanReviewTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("PO_ALLOW_TEST_MIGRATION") != "yes":
            raise RuntimeError("test migration not authorized")
        cls.store = PostgresStore(os.environ["PO_TEST_DATABASE_URL"])
        with cls.store.connect() as conn:
            conn.execute(Path("pilotage/migration.sql").read_text())

    async def asyncSetUp(self):
        self.tenant, self.actor = uuid4(), uuid4()
        self.env = patch.dict(os.environ, {
            "EDITORIAL_API_TOKEN": "t" * 32,
            "EDITORIAL_TENANT_ID": str(self.tenant), "EDITORIAL_ACTOR_ID": str(self.actor)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(app.dependency_overrides.clear)
        app.dependency_overrides[get_store] = lambda: self.store
        run, _ = self.store.start(self.tenant, self.actor, uuid4(), Brief(topic="Ys").model_dump())
        self.run_id = UUID(run["id"])
        for step, parsed in zip(("analysis", "storyboard"), outputs()):
            self.store.begin_step(self.tenant, self.actor, self.run_id, step, "prompt")
            self.store.save_step(self.tenant, self.actor, self.run_id, step, "prompt",
                                 {"response": json.dumps(parsed), "finish_reason": "stop"}, parsed)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.headers = {"Authorization": "Bearer " + "t" * 32}

    async def review(self, step="analysis", action="accept", revision=0, **kwargs):
        return await self.client.post(f"/editorial/runs/{self.run_id}/steps/{step}/review",
            headers=self.headers, json={"action": action, "expected_revision": revision, **kwargs})

    def current(self):
        return self.store.get(self.tenant, self.run_id)

    async def test_two_acceptances_approve_run_and_current_scenario(self):
        self.assertEqual((await self.review()).status_code, 200)
        response = await self.review("storyboard", revision=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "approved")
        self.assertFalse(response.json()["requires_human_validation"])
        with self.store.connect() as conn:
            content = conn.execute("SELECT content FROM po_entity WHERE tenant_id=%s AND entity_id=%s",
                (self.tenant, UUID(response.json()["scenario_id"]))).fetchone()[0]
        self.assertFalse(content["requires_human_validation"])
        self.assertEqual((await self.review(revision=2)).status_code, 409)

    async def test_revise_preserves_snapshot_and_requires_explicit_acceptance(self):
        old = self.store.history(self.tenant, self.run_id)
        original_scenario = self.current()["scenario_id"]
        revised = copy.deepcopy(outputs()[1])
        revised["title"] = "Version humaine"
        self.assertEqual((await self.review("storyboard", "reject", comment="A revoir")).status_code, 200)
        response = await self.review("storyboard", "revise", 1, comment="Correction", revised_output=revised)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["storyboard"]["title"], "Version humaine")
        self.assertNotEqual(response.json()["scenario_id"], original_scenario)
        self.assertTrue(response.json()["requires_human_validation"])
        self.assertEqual(self.store.history(self.tenant, self.run_id), old)
        self.assertEqual((await self.review(revision=2)).status_code, 200)
        self.assertEqual((await self.review("storyboard", revision=3)).json()["status"], "approved")

    async def test_analysis_revision_invalidates_storyboard(self):
        self.assertEqual((await self.review("storyboard")).status_code, 200)
        changed = outputs()[0] | {"angle": "Nouvel angle"}
        self.assertEqual((await self.review("analysis", "revise", 1, comment="Angle", revised_output=changed)).status_code, 200)
        self.assertEqual((await self.review("analysis", revision=2)).status_code, 200)
        self.assertEqual((await self.review("storyboard", revision=3)).status_code, 409)
        self.assertEqual((await self.review("storyboard", "revise", 3, comment="Aligne", revised_output=outputs()[1])).status_code, 200)
        self.assertEqual((await self.review("storyboard", revision=4)).json()["status"], "approved")

    async def test_authentication_is_required(self):
        response = await self.client.post(f"/editorial/runs/{self.run_id}/steps/analysis/review",
                                          json={"action": "accept", "expected_revision": 0})
        self.assertEqual(response.status_code, 401)

    async def test_other_tenant_cannot_review_or_read_history(self):
        with patch.dict(os.environ, {"EDITORIAL_TENANT_ID": str(uuid4())}):
            self.assertEqual((await self.review()).status_code, 404)
            response = await self.client.get(f"/editorial/runs/{self.run_id}/reviews", headers=self.headers)
            self.assertEqual(response.status_code, 404)
        self.assertNotIn("review_revision", self.current())

    async def test_invalid_payloads_do_not_write(self):
        for body in ({"action": "reject", "expected_revision": 0},
                     {"action": "accept", "expected_revision": True},
                     {"action": "revise", "expected_revision": 0, "comment": "Correction", "revised_output": outputs()[1]},
                     {"action": "accept", "expected_revision": 0, "revised_output": outputs()[0]},
                     {"action": "revise", "expected_revision": 0, "comment": "  ", "revised_output": outputs()[0]}):
            with self.subTest(body=body):
                response = await self.client.post(f"/editorial/runs/{self.run_id}/steps/analysis/review", headers=self.headers, json=body)
                self.assertEqual(response.status_code, 422)
        invalid = copy.deepcopy(outputs()[1])
        invalid["scenes"][0]["duration_seconds"] = 21
        self.assertEqual((await self.review("storyboard", "revise", comment="Duree", revised_output=invalid)).status_code, 422)
        self.assertNotIn("review_revision", self.current())

    async def test_stale_or_concurrent_decisions_have_one_winner(self):
        import asyncio
        responses = await asyncio.gather(self.review(), self.review(action="reject", comment="Non"))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        self.assertEqual(self.current()["review_revision"], 1)
        with self.store.connect() as conn:
            count = conn.execute("SELECT count(*) FROM po_entity WHERE tenant_id=%s AND content->>'type'='editorial_review'",
                                 (self.tenant,)).fetchone()[0]
        self.assertEqual(count, 1)

    async def test_failed_transaction_leaves_no_review_or_audit(self):
        before = self.current()
        with self.store.connect() as conn:
            initial = conn.execute("SELECT count(*) FROM po_audit WHERE correlation_id=%s", (self.run_id,)).fetchone()[0]
        original = self.store._write
        def fail(conn, *args, **kwargs):
            original(conn, *args, **kwargs)
            if args[3] == "result" and args[5].get("type") == "editorial_review":
                raise psycopg.errors.SerializationFailure("injected")
        with patch.object(self.store, "_write", side_effect=fail):
            self.assertEqual((await self.review()).status_code, 503)
        self.assertEqual(self.current(), before)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM po_audit WHERE correlation_id=%s", (self.run_id,)).fetchone()[0], initial)

    async def test_history_is_paginated_and_attributed(self):
        for revision in range(3):
            self.assertEqual((await self.review(action="reject", revision=revision, comment="A revoir")).status_code, 200)
        path = f"/editorial/runs/{self.run_id}/reviews"
        page = (await self.client.get(path+"?limit=2", headers=self.headers)).json()
        self.assertEqual([r["revision"] for r in page["reviews"]], [3, 2])
        self.assertEqual(page["next_before_revision"], 2)
        self.assertEqual(page["reviews"][0]["actor_id"], str(self.actor))
        older = (await self.client.get(path+"?limit=2&before_revision=2", headers=self.headers)).json()
        self.assertEqual([r["revision"] for r in older["reviews"]], [1])
        self.assertIsNone(older["next_before_revision"])
        self.assertEqual((await self.client.get(path+"?limit=51", headers=self.headers)).status_code, 422)

    async def test_incomplete_failed_or_unknown_run_cannot_be_reviewed(self):
        pending, _ = self.store.start(self.tenant, self.actor, uuid4(), Brief(topic="Pending").model_dump())
        path = f"/editorial/runs/{pending['id']}/steps/analysis/review"
        body = {"action": "accept", "expected_revision": 0}
        self.assertEqual((await self.client.post(path, headers=self.headers, json=body)).status_code, 409)
        run_id = UUID(pending["id"])
        self.store.begin_step(self.tenant, self.actor, run_id, "analysis", "prompt")
        self.store.save_step(self.tenant, self.actor, run_id, "analysis", "prompt",
                             {"response": "invalid"}, None, "invalid_structured_output")
        self.assertEqual((await self.client.post(path, headers=self.headers, json=body)).status_code, 409)
        self.assertEqual((await self.client.post(f"/editorial/runs/{uuid4()}/steps/analysis/review",
                                               headers=self.headers, json=body)).status_code, 404)

    async def test_revision_keeps_original_scenario_and_audit_outbox_atomic(self):
        original_id = self.current()["scenario_id"]
        with self.store.connect() as conn:
            original = conn.execute("SELECT content FROM po_entity WHERE tenant_id=%s AND entity_id=%s",
                                    (self.tenant, UUID(original_id))).fetchone()[0]
        revised = copy.deepcopy(outputs()[1])
        revised["scenes"][0]["narration"] = "Narration humaine"
        response = await self.review("storyboard", "revise", comment="Narration", revised_output=revised)
        self.assertEqual(response.status_code, 200)
        run = response.json()
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT content FROM po_entity WHERE tenant_id=%s AND entity_id=%s",
                (self.tenant, UUID(original_id))).fetchone()[0], original)
            first = conn.execute("SELECT content FROM po_entity WHERE tenant_id=%s AND entity_id=%s",
                (self.tenant, UUID(run["scene_ids"][0]))).fetchone()[0]
            self.assertEqual(first["narration"], "Narration humaine")
            self.assertEqual(first["scenario_id"], run["scenario_id"])
            counts = conn.execute("SELECT (SELECT count(*) FROM po_audit WHERE correlation_id=%s),"
                                  "(SELECT count(*) FROM po_outbox o JOIN po_audit a USING(event_id) WHERE a.correlation_id=%s)",
                                  (self.run_id, self.run_id)).fetchone()
            self.assertEqual(counts[0], counts[1])

    async def test_invalid_history_bounds_and_unauthenticated_history(self):
        path = f"/editorial/runs/{self.run_id}/reviews"
        self.assertEqual((await self.client.get(path)).status_code, 401)
        for suffix in ("?limit=0", "?before_revision=0", "?before_revision=2147483648"):
            self.assertEqual((await self.client.get(path+suffix, headers=self.headers)).status_code, 422)

    async def test_final_approval_revalidates_previously_accepted_result(self):
        self.assertEqual((await self.review("storyboard")).status_code, 200)
        run = self.current()
        run["storyboard"]["scenes"][0]["duration_seconds"] = 21
        with self.store.connect() as conn:
            conn.execute("UPDATE po_entity SET content=%s::jsonb WHERE tenant_id=%s AND entity_id=%s",
                         (json.dumps(run), self.tenant, self.run_id))
        response = await self.review("analysis", revision=1)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.current()["review_revision"], 1)
        self.assertTrue(self.current()["requires_human_validation"])
