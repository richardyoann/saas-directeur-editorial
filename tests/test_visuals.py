"""Real PostgreSQL / ASGI vertical journey for characters and private images.

Provider is deliberately mocked: a Qwen-only PC cannot create image pixels.
No test writes to the user's application database or generated-media directory.
"""
import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4, uuid5

import httpx

from apps.api.main import app
from editorial.api import get_store
from editorial.models import Brief
from editorial.store import PostgresStore
from editorial.visuals import (ImageUnavailable, characters, image_prompt,
                               render_png, save_png, load_png, validate_png)
from test_editorial import outputs


# Tiny valid PNG fixture. No new Pillow dependency.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


class VisualContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_cast_is_schema_valid_and_old_stories_work(self):
        from editorial.models import Storyboard
        old = Storyboard.model_validate(outputs()[1])
        self.assertEqual(old.cast, [])
        new = outputs()[1]
        new["cast"] = [{
            "name": "Un marin", "appearance": "Bonnet bleu, manteau usé",
            "personality": "Audacieux", "role": "Témoin"
        }]
        self.assertEqual(Storyboard.model_validate(new).cast[0].role, "Témoin")

    async def test_character_names_remain_consistent(self):
        board = {"scenes": [{"characters": ["L'Ankou", "Marin"]},
                            {"characters": ["l'ankou", "Marin", "Roi"]}]}
        c = characters(board)
        self.assertEqual([x["name"] for x in c], ["L'Ankou", "Marin", "Roi"])
        self.assertEqual(c[0]["scenes"], [1, 2])

    async def test_qwen_character_profiles_anchor_multiple_scenes(self):
        board = outputs()[1]
        board["cast"] = [{"name": "Un marin", "appearance": "Manteau rouge et barbe grise",
                          "personality": "Courageux", "role": "Héros"}]
        people = characters(board)
        self.assertEqual(people[0]["appearance"], "Manteau rouge et barbe grise")
        prompt = image_prompt({"storyboard": board}, 2)
        self.assertIn("Manteau rouge et barbe grise", prompt)

    async def test_public_or_credentialed_image_provider_is_rejected(self):
        from editorial.visuals import private_image_url
        self.assertFalse(private_image_url("https://api.public.example"))
        self.assertFalse(private_image_url("http://admin:secret@127.0.0.1:8082"))
        self.assertFalse(private_image_url("http://127.0.0.1:8082/other"))
        self.assertTrue(private_image_url("http://127.0.0.1:8082"))
        self.assertTrue(private_image_url("http://172.31.48.1:8082"))

    async def test_prompt_contains_scene_information(self):
        scene = outputs()[1]["scenes"][0]
        text = image_prompt({"storyboard": {"scenes": [scene]}}, 1)
        self.assertIn(scene["landscape"], text)
        self.assertIn(scene["image_prompt"], text)
        self.assertIn(scene["characters"][0], text)
        with self.assertRaises(ValueError):
            image_prompt({"storyboard": {"scenes": [scene]}}, 2)

    async def test_image_provider_requires_real_single_png(self):
        def handler(request):
            self.assertEqual(request.url.path, "/v1/images/generations")
            self.assertEqual(request.method, "POST")
            self.assertEqual(__import__("json").loads(request.content)["response_format"], "b64_json")
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG).decode()}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            raw = await render_png(client, "http://127.0.0.1:8082", "Une côte bretonne")
        self.assertEqual(raw, PNG)
        self.assertEqual(validate_png(raw), (1, 1))
        async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"data": [{"url": "https://untrusted"}]})
        )) as client:
            with self.assertRaises(ImageUnavailable):
                await render_png(client, "http://127.0.0.1:8082", "test")
        with self.assertRaises(ImageUnavailable):
            validate_png(b"<script>alert(1)</script>")

    async def test_private_file_roundtrip_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"EDITORIAL_MEDIA_ROOT": directory}):
                ids = (uuid4(), uuid4(), uuid4())
                path = save_png(*ids, PNG)
                self.assertTrue(path.is_file())
                self.assertEqual(load_png(*ids), PNG)
                with self.assertRaises(ImageUnavailable):
                    save_png(*ids, PNG)
                with self.assertRaises(ImageUnavailable):
                    load_png(ids[0], ids[1], uuid4())


@unittest.skipUnless(os.getenv("PO_TEST_DATABASE_URL"), "disposable CI PostgreSQL required")
class VisualIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        if os.getenv("PO_ALLOW_TEST_MIGRATION") != "yes":
            raise RuntimeError("Test database migration not authorized")
        cls.store = PostgresStore(os.environ["PO_TEST_DATABASE_URL"])
        with cls.store.connect() as conn:
            conn.execute(Path("pilotage/migration.sql").read_text())

    async def asyncSetUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.tenant, self.actor, self.key = uuid4(), uuid4(), uuid4()
        env = patch.dict(os.environ, {
            "EDITORIAL_API_TOKEN": "t" * 48,
            "EDITORIAL_WEB_PASSWORD": "w" * 48,
            "EDITORIAL_TENANT_ID": str(self.tenant),
            "EDITORIAL_ACTOR_ID": str(self.actor),
            "IMAGE_BASE_URL": "http://127.0.0.1:8082",
            "EDITORIAL_MEDIA_ROOT": self.media.name,
        })
        env.start()
        self.addCleanup(env.stop)
        app.dependency_overrides[get_store] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                        base_url="http://localhost")
        self.addAsyncCleanup(self.client.aclose)
        self.auth = {"Authorization": "Bearer " + "t" * 48}
        run, _ = self.store.start(self.tenant, self.actor, self.key, Brief(topic="Ys").model_dump())
        self.run_id = UUID(run["id"])
        for step, parsed in zip(("analysis", "storyboard"), outputs()):
            self.store.begin_step(self.tenant, self.actor, self.run_id, step, "prompt")
            self.store.save_step(self.tenant, self.actor, self.run_id, step, "prompt",
                                 {"response": "fixture", "finish_reason": "stop"}, parsed)

    async def approve(self):
        self.store.review(self.tenant, self.actor, self.run_id, "analysis",
                          {"action": "accept", "expected_revision": 0})
        self.store.review(self.tenant, self.actor, self.run_id, "storyboard",
                          {"action": "accept", "expected_revision": 1})

    async def test_unapproved_or_unconfigured_image_is_never_generated(self):
        url = f"/editorial/runs/{self.run_id}/scenes/1/image"
        self.assertEqual((await self.client.post(url)).status_code, 401)
        self.assertEqual((await self.client.get(url)).status_code, 401)
        self.assertEqual((await self.client.post(url, headers=self.auth)).status_code, 409)
        with patch.dict(os.environ, {"IMAGE_BASE_URL": ""}):
            self.assertEqual((await self.client.post(url, headers=self.auth)).status_code, 503)
        plan = (await self.client.get(f"/editorial/runs/{self.run_id}/visuals",
                                     headers=self.auth)).json()
        self.assertFalse(plan["approved"])
        self.assertEqual(len(plan["characters"]), 1)
        self.assertEqual(len(plan["scenes"]), 3)

    async def test_approved_story_to_png_and_audit(self):
        await self.approve()
        base = f"/editorial/runs/{self.run_id}"
        path = base + "/scenes/1/image"
        with patch("editorial.api.render_png", new_callable=AsyncMock, return_value=PNG) as render:
            response = await self.client.post(path, headers=self.auth)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(render.await_count, 1)
        self.assertEqual(response.json()["status"], "ready")
        self.assertEqual((await self.client.get(path, headers=self.auth)).content, PNG)
        # A browser session (not a bearer token embedded in JS) can preview it.
        self.assertEqual((await self.client.get(
            f"/studio/api/runs/{self.run_id}/scenes/1/image")).status_code, 401)
        login = await self.client.post("/studio/session",
            headers={"Origin": "http://localhost"}, json={"password": "w" * 48})
        self.assertEqual(login.status_code, 200)
        preview = await self.client.get(
            f"/studio/api/runs/{self.run_id}/scenes/1/image")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.content, PNG)
        self.assertEqual(preview.headers.get("cache-control"), "no-store")
        duplicate = await self.client.post(path, headers=self.auth)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual((await self.client.get(base + "/scenes/2/image", headers=self.auth)).status_code, 404)
        plan = (await self.client.get(base + "/visuals", headers=self.auth)).json()
        self.assertTrue(plan["approved"])
        self.assertEqual([x["image_status"] for x in plan["scenes"]],
                         ["ready", "not_generated", "not_generated"])
        run = self.store.get(self.tenant, self.run_id)
        asset_id = uuid5(UUID(run["scene_ids"][0]), "private-image-v1")
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT content FROM po_entity WHERE tenant_id=%s AND kind='result' "
                "AND entity_id=%s AND NOT deleted", (self.tenant, asset_id)
            ).fetchone()[0]
            self.assertEqual(row["status"], "ready")
            self.assertEqual(row["mime_type"], "image/png")
            count = conn.execute(
                "SELECT COUNT(*) FROM po_audit a JOIN po_outbox o USING(event_id) "
                "WHERE a.tenant_id=%s AND a.entity_id=%s",
                (self.tenant, asset_id)
            ).fetchone()[0]
        self.assertEqual(count, 2)

    async def test_image_failure_is_audited_without_autoreplay(self):
        await self.approve()
        url = f"/editorial/runs/{self.run_id}/scenes/1/image"
        with patch("editorial.api.render_png", new_callable=AsyncMock,
                   side_effect=ImageUnavailable()):
            response = await self.client.post(url, headers=self.auth)
        self.assertEqual(response.status_code, 502)
        plan = (await self.client.get(f"/editorial/runs/{self.run_id}/visuals",
                                     headers=self.auth)).json()
        self.assertEqual(plan["scenes"][0]["image_status"], "failed")
        self.assertEqual((await self.client.post(url, headers=self.auth)).status_code, 409)


if __name__ == "__main__":
    unittest.main()
