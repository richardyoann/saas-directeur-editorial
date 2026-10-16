"""Isolated private GitHub cockpit contract tests. No GitHub or PC side effects."""
import os
import unittest
from unittest.mock import patch

import httpx

from apps.api.main import app
from apps.api import studio


SHA = "a" * 40


class GitHubConceptionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        studio.sessions.clear()
        studio.failures.clear()
        self.env = patch.dict(os.environ, {
            "EDITORIAL_WEB_PASSWORD": "w" * 48,
            "EDITORIAL_API_TOKEN": "t" * 48,
            "EDITORIAL_GITHUB_READ_TOKEN": "r" * 48,
            "EDITORIAL_GITHUB_REPOSITORY": "richardyoann/saas-directeur-editorial",
            # Even a stale opt-in must never re-enable Studio writes.
            "EDITORIAL_GITHUB_DELIVERY_WRITE_ENABLED": "true",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        )
        self.addAsyncCleanup(self.client.aclose)
        self.calls = []
        self.regression_success = True
        self.head_sha = SHA

    async def login(self):
        response = await self.client.post(
            "/studio/session", json={"password": "w" * 48},
            headers={"Origin": "http://localhost"}
        )
        self.assertEqual(response.status_code, 200)
        return {
            "Origin": "http://localhost",
            "X-CSRF-Token": response.json()["csrf"],
        }

    async def fake_gh(self, method, suffix, *, token, payload=None):
        self.calls.append((method, suffix, token, payload))
        if suffix == "/issues?state=all&per_page=100":
            return [
                {"number": 2, "title": "[EPIC-001] Qwen", "state": "open",
                 "created_at": "2026-10-01T08:00:00Z"},
                {"number": 3, "title": "Task", "state": "open"},
                {"number": 4, "title": "Fake", "pull_request": {}},
            ]
        if suffix == "/pulls?state=all&per_page=70":
            return [{"number": 92, "title": "Interface", "merged_at": None,
                     "state": "open", "draft": True,
                     "head": {"sha": SHA}}]
        if suffix == "/actions/workflows/local-delivery.yml/runs?per_page=70":
            return {"workflow_runs": [
                {"id": 123, "head_sha": SHA, "status": "completed",
                 "conclusion": "success", "updated_at": "2026-10-01T11:00:00Z"},
            ]}
        if suffix == "/actions/variables/LOCAL_PC_ENABLED":
            return {"value": "true"}
        if suffix == "/pulls/92":
            return {"state": "closed", "merged_at": "2026-10-01T09:00:00Z",
                    "base": {"ref": "main"}, "merge_commit_sha": SHA}
        if suffix == "/branches/main":
            return {"commit": {"sha": self.head_sha}}
        if suffix.startswith("/actions/workflows/regression.yml/runs?"):
            return {"workflow_runs": [{"head_sha": SHA,
                "head_branch": "main", "event": "push",
                "status": "completed",
                "conclusion": "success" if self.regression_success else "failure"}]}
        if suffix == "/actions/variables/LOCAL_PC_APPROVED_SHA":
            return {"value": "b" * 40} if method == "GET" else {}
        if suffix == "/actions/workflows/local-delivery.yml/dispatches":
            return {}
        self.fail("Unexpected GitHub request: " + suffix)

    async def test_read_requires_session_and_returns_live_categories(self):
        with patch.object(studio, "_gh", side_effect=self.fake_gh):
            unauth = await self.client.get("/studio/api/conception")
            self.assertEqual(unauth.status_code, 401)
            await self.login()
            response = await self.client.get("/studio/api/conception")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data["epics"]), 1)
            self.assertEqual(data["epics"][0]["number"], 2)
            self.assertEqual(data["pull_requests"][0]["number"], 92)
            self.assertEqual(data["deliveries"][0]["id"], 123)
            self.assertIs(data["delivery_control_enabled"], False)
            self.assertNotIn("token", response.text.lower())
            self.assertIn("no-store", response.headers["cache-control"])

    async def test_delivery_endpoint_is_fail_closed_and_has_no_github_side_effect(self):
        headers = await self.login()
        url = "/studio/api/conception/pulls/92/deliver"
        payload = {"confirm": "AUTORISER PC", "sha": SHA,
                   "approval_secret": "s" * 48}
        with patch.object(studio, "_gh", side_effect=self.fake_gh):
            for _ in range(2):
                response = await self.client.post(url, json=payload, headers=headers)
                self.assertEqual(response.status_code, 403)
                self.assertIn("non déclenchable depuis Studio", response.json()["detail"])
        self.assertEqual(self.calls, [])
