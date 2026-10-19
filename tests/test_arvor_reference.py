"""Arvor reference shell tests: authentication, safe GitHub reads, assets."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx

from apps.api.main import app
from apps.api import studio

ROOT = Path(__file__).resolve().parents[1]


class ArvorReferenceStaticTests(unittest.TestCase):
    def test_reference_assets_are_whitelisted(self):
        html=(ROOT/"apps/web/studio.html").read_text()
        api=(ROOT/"apps/api/studio.py").read_text()
        for asset in ("arvor_reference.js","arvor_reference.css"):
            self.assertTrue((ROOT/"apps/web"/asset).is_file())
            self.assertIn("/studio/assets/"+asset,html)
            self.assertIn('"'+asset+'"',api)

    def test_current_studio_shell_keeps_its_existing_ui_contract(self):
        html=(ROOT/"apps/web/studio.html").read_text()
        for id_ in ("loginForm","conceptionNav","storyCards","home","count"):
            self.assertIn('id="'+id_+'"',html)
        js=(ROOT/"apps/web/arvor_reference.js").read_text()
        for route in ("/studio/api/runs?limit=50",
                      "/studio/api/conception",
                      "/studio/api/conception/commits",
                      "/studio/api/conception/ci"):
            self.assertIn(route,js)
        self.assertNotIn("LOCAL_PC_APPROVED_SHA",js)
        self.assertNotIn("innerHTML",js)


class ArvorReferenceEndpoints(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        studio.sessions.clear()
        studio.failures.clear()
        self.env=patch.dict(os.environ,{
            "EDITORIAL_WEB_PASSWORD":"w"*48,
            "EDITORIAL_API_TOKEN":"t"*48,
            "EDITORIAL_GITHUB_READ_TOKEN":"r"*48,
            "EDITORIAL_GITHUB_REPOSITORY":"richardyoann/saas-directeur-editorial",
            "EDITORIAL_TENANT_ID":str(uuid4()),
            "EDITORIAL_ACTOR_ID":str(uuid4()),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client=httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),base_url="http://localhost")
        self.addAsyncCleanup(self.client.aclose)

    async def sign_in(self):
        response=await self.client.post("/studio/session",
            json={"password":"w"*48},headers={"Origin":"http://localhost"})
        self.assertEqual(response.status_code,200)

    async def test_commits_require_session_and_map_real_fields(self):
        self.assertEqual((await self.client.get(
            "/studio/api/conception/commits")).status_code,401)
        await self.sign_in()
        rows=[{"sha":"a"*40,"commit":{"message":"fix: correction\nmore",
              "committer":{"date":"2026-10-16T15:00:00Z"}},
              "html_url":"https://github.com/richardyoann/saas-directeur-editorial/commit/"+("a"*40)}]
        with patch.object(studio,"_gh",return_value=rows) as gh:
            response=await self.client.get("/studio/api/conception/commits?limit=3")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["commits"][0]["message"],"fix: correction")
        self.assertFalse(response.json()["partial"])
        gh.assert_awaited_once()
        self.assertEqual(gh.await_args.args[:2],("GET","/commits?sha=main&per_page=3"))

    async def test_ci_reports_proofs_without_pc_claim(self):
        await self.sign_in()
        rows={"workflow_runs":[{"id":12,"head_sha":"b"*40,"event":"push",
             "status":"completed","conclusion":"failure","created_at":"2026-10-16T15:00:00Z"}]}
        with patch.object(studio,"_gh",return_value=rows):
            response=await self.client.get("/studio/api/conception/ci?limit=10")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["runs"][0]["conclusion"],"failure")
        self.assertNotIn("installed_live",response.text)
        self.assertEqual((await self.client.get(
            "/studio/api/conception/ci?limit=101")).status_code,422)

    async def test_reference_assets_have_strict_csp(self):
        response=await self.client.get("/studio/assets/arvor_reference.js")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers["content-type"].split(";")[0],"text/javascript")
        self.assertIn("default-src 'none'",response.headers["content-security-policy"])


if __name__=="__main__":
    unittest.main()
