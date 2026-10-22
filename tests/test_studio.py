"""HTTP contract tests for the private studio (no actual user DB or LLM)."""
import os
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx

from apps.api.main import app
from apps.api.studio import failures, sessions
from editorial.api import get_store
from editorial.store import RunMissing


class FakeStore:
    def __init__(self):
        self.tenant = None
        self.run_id = uuid4()

    def list_runs(self, tenant, limit, before):
        self.tenant = tenant
        return {"runs": [{"id": str(self.run_id), "topic": "Ville d'Ys",
                          "title": "Ys sous les flots", "status": "waiting_validation",
                          "created_at": "2026-10-14T00:00:00+00:00",
                          "review_revision": 0}], "next_before": None}

    def get(self, tenant, run_id):
        self.tenant = tenant
        if run_id != self.run_id:
            raise RunMissing()
        return {"id": str(run_id), "status": "waiting_validation",
                "review_revision": 0, "analysis": {"angle": "La mer",
                "message": "Une légende", "historical_checks": []}}

    def reconcile_interrupted(self, tenant, actor, run_id):
        self.tenant = tenant
        self.actor = actor
        if run_id != self.run_id:
            raise RunMissing()
        return {"id": str(run_id), "status": "failed", "error_code": "run_interrupted"}

    def review(self, tenant, actor, run_id, step, decision):
        if run_id != self.run_id:
            raise RunMissing()
        return {"id": str(run_id), "status": "waiting_validation",
                "review_revision": 1, "reviewed_step": step, "action": decision.action,
                "actor": str(actor)}


class StudioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sessions.clear()
        failures.clear()
        self.store = FakeStore()
        self.tenant, self.actor = uuid4(), uuid4()
        self.env = patch.dict(os.environ, {
            "EDITORIAL_WEB_PASSWORD": "w" * 48,
            "EDITORIAL_API_TOKEN": "t" * 48,
            "EDITORIAL_TENANT_ID": str(self.tenant),
            "EDITORIAL_ACTOR_ID": str(self.actor),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        app.dependency_overrides[get_store] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost")
        self.addAsyncCleanup(self.client.aclose)
        self.origin = {"Origin": "http://localhost"}

    async def sign_in(self):
        response = await self.client.post("/studio/session",
            json={"password": "w" * 48}, headers=self.origin)
        self.assertEqual(response.status_code, 200)
        self.assertIn("httponly", response.headers["set-cookie"].lower())
        self.assertIn("samesite=strict", response.headers["set-cookie"].lower())
        return response.json()["csrf"]

    async def test_unconfigured_and_unauthenticated_fail_closed(self):
        self.assertEqual((await self.client.get("/studio/api/runs")).status_code, 401)
        self.assertEqual((await self.client.get("/studio/session")).json()["authenticated"], False)
        with patch.dict(os.environ, {"EDITORIAL_WEB_PASSWORD": "short"}):
            response = await self.client.post("/studio/session",
                json={"password": "short"}, headers=self.origin)
            self.assertEqual(response.status_code, 503)
        self.assertEqual((await self.client.get("/studio")).status_code, 200)

    async def test_session_list_detail_logout(self):
        csrf = await self.sign_in()
        runs = await self.client.get("/studio/api/runs")
        self.assertEqual(runs.status_code, 200)
        self.assertEqual(runs.json()["runs"][0]["topic"], "Ville d'Ys")
        self.assertEqual(self.store.tenant, self.tenant)
        detail = await self.client.get("/studio/api/runs/" + str(self.store.run_id))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual((await self.client.get("/studio/api/runs/" + str(uuid4()))).status_code, 404)
        out = await self.client.post("/studio/logout", headers=self.origin | {"X-CSRF-Token": csrf})
        self.assertEqual(out.status_code, 200)
        self.assertEqual((await self.client.get("/studio/api/runs")).status_code, 401)

    async def test_csrf_and_origin_before_review(self):
        csrf = await self.sign_in()
        url = "/studio/api/runs/" + str(self.store.run_id) + "/steps/analysis/review"
        payload = {"action": "accept", "expected_revision": 0}
        self.assertEqual((await self.client.post(url, json=payload, headers=self.origin)).status_code, 403)
        self.assertEqual((await self.client.post(url, json=payload, headers={"X-CSRF-Token": csrf})).status_code, 403)
        response = await self.client.post(url, json=payload,
            headers=self.origin | {"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["actor"], str(self.actor))
        self.assertEqual((await self.client.post(url.replace("/analysis/", "/invalid/"),
            json=payload, headers=self.origin | {"X-CSRF-Token": csrf})).status_code, 422)

    async def test_reconcile_requires_session_csrf_and_tenant_identity(self):
        url = f"/studio/api/runs/{self.store.run_id}/reconcile"
        self.assertEqual((await self.client.post(url, headers=self.origin)).status_code, 401)
        csrf = await self.sign_in()
        self.assertEqual((await self.client.post(url, headers=self.origin)).status_code, 403)
        self.assertEqual((await self.client.post(
            url, headers={"X-CSRF-Token": csrf})).status_code, 403)
        response = await self.client.post(url, headers=self.origin | {"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error_code"], "run_interrupted")
        self.assertEqual(self.store.tenant, self.tenant)
        self.assertEqual(self.store.actor, self.actor)
        other = f"/studio/api/runs/{uuid4()}/reconcile"
        self.assertEqual((await self.client.post(
            other, headers=self.origin | {"X-CSRF-Token": csrf})).status_code, 404)

    async def test_input_validation_and_assets_do_not_expose_secret(self):
        csrf = await self.sign_in()
        self.assertEqual((await self.client.get("/studio/api/runs?limit=51")).status_code, 422)
        self.assertEqual((await self.client.get("/studio/api/runs?before=nope")).status_code, 422)
        result = await self.client.post("/studio/api/runs", json={"topic": "Ys"},
            headers=self.origin | {"X-CSRF-Token": csrf, "Idempotency-Key": "bad"})
        self.assertEqual(result.status_code, 422)
        for path in ["/studio", "/studio/assets/studio.js", "/studio/assets/studio.css"]:
            response = await self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("t" * 48, response.text)
            self.assertIn("no-store", response.headers["cache-control"])
            self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])

    async def test_login_throttling(self):
        for _ in range(5):
            response = await self.client.post("/studio/session",
                json={"password": "wrong"}, headers=self.origin)
            self.assertEqual(response.status_code, 401)
        response = await self.client.post("/studio/session",
            json={"password": "w" * 48}, headers=self.origin)
        self.assertEqual(response.status_code, 429)

    async def test_remote_http_is_rejected(self):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("192.0.2.2", 4321)),
                                     base_url="http://example.test") as remote:
            self.assertEqual((await remote.get("/studio")).status_code, 403)
            self.assertEqual((await remote.get("/studio/session")).status_code, 403)

    async def test_interruption_signal_is_readonly_and_tenant_scoped(self):
        from datetime import datetime, timedelta, timezone
        await self.sign_in()
        run={'id':str(self.store.run_id),'status':'running','current_step':{
            'name':'analysis','started_at':(datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat()}}
        with patch.object(self.store,'get',return_value=run) as get_run, \
             patch.object(self.store,'reconcile_interrupted') as reconcile:
            response=await self.client.get('/studio/api/runs/'+str(self.store.run_id))
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.json()['recovery']['reconciliation_required'])
            self.assertFalse(response.json()['recovery']['automatic_retry_allowed'])
            get_run.assert_called_once_with(self.tenant,self.store.run_id)
            reconcile.assert_not_called()
            self.assertNotIn('recovery',run)

    async def test_all_mutations_refuse_csrf_before_relay(self):
        from unittest.mock import AsyncMock
        csrf=await self.sign_in()
        run='/studio/api/runs/'+str(self.store.run_id)
        paths=['/studio/api/runs',run+'/reconcile',run+'/steps/analysis/review',run+'/scenes/1/image','/studio/logout']
        variants=[{'X-CSRF-Token':csrf},{'Origin':'https://untrusted.invalid','X-CSRF-Token':csrf},self.origin|{'X-CSRF-Token':'incorrect'}]
        with patch.object(app.state, 'internal_client', create=True) as internal:
            internal.request = AsyncMock()
            for path in paths:
                for headers in variants:
                    with self.subTest(path=path,headers=list(headers)):
                        response=await self.client.post(path,json={},headers=headers)
                        self.assertEqual(response.status_code,403)
            internal.request.assert_not_awaited()


class ConcurrentLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_streamed_passwords_respect_existing_attempt_budget(self):
        import asyncio
        sessions.clear()
        failures.clear()
        self.addCleanup(sessions.clear)
        self.addCleanup(failures.clear)
        async def fragmented_body():
            yield b'{"password":'
            await asyncio.sleep(0.01)
            yield b'"incorrect"}'
        with patch.dict(os.environ, {'EDITORIAL_WEB_PASSWORD':'w'*48,'EDITORIAL_API_TOKEN':'t'*48}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as client:
                replies=await asyncio.gather(*[client.post('/studio/session',
                    headers={'Origin':'http://localhost','Content-Type':'application/json'},
                    content=fragmented_body()) for _ in range(20)])
        self.assertEqual(sum(r.status_code==401 for r in replies),5)
        self.assertEqual(sum(r.status_code==429 for r in replies),15)
        self.assertEqual(len(sessions),0)
