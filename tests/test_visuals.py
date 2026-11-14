"""Real PostgreSQL / ASGI vertical journey for characters and private images.

Provider is deliberately mocked: a Qwen-only PC cannot create image pixels.
No test writes to the user's application database or generated-media directory.
"""
import base64
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
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
    async def test_shared_rules_preserve_historical_exports_and_exception_identity(self):
        from editorial import media_rules, visuals
        for name in ("MAX_PNG_BYTES", "PNG_MAGIC", "IMAGE_PARAMETERS", "ImageUnavailable",
                     "ImagePromptTooLong", "characters", "image_prompt", "image_provenance",
                     "validate_png", "private_image_url"):
            with self.subTest(name=name):
                self.assertIs(getattr(visuals, name), getattr(media_rules, name))
        with self.assertRaises(visuals.ImageUnavailable):
            media_rules.validate_png(b"invalid")

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
        self.assertFalse(private_image_url("http://169.254.169.254"))
        self.assertFalse(private_image_url("http://0.0.0.0:8082"))
        self.assertFalse(private_image_url("http://[fe80::1]:8082"))
        self.assertFalse(private_image_url("http://[::ffff:169.254.169.254]:8082"))
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
            self.assertEqual(__import__("json").loads(request.content)["output_format"], "png")
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
        for step, parsed in zip(("analysis", "storyboard"), outputs(), strict=True):
            self.store.begin_step(self.tenant, self.actor, self.run_id, step, "prompt")
            self.store.save_step(self.tenant, self.actor, self.run_id, step, "prompt",
                                 {"response": "fixture", "finish_reason": "stop"}, parsed)

    async def approve(self):
        self.store.review(self.tenant, self.actor, self.run_id, "analysis",
                          {"action": "accept", "expected_revision": 0})
        self.store.review(self.tenant, self.actor, self.run_id, "storyboard",
                          {"action": "accept", "expected_revision": 1})

    async def test_minio_image_reference_is_audited_and_old_local_images_still_work(self):
        await self.approve()
        url = f"/editorial/runs/{self.run_id}/scenes/1/image"
        api = MagicMock()
        api.put_object.return_value = {"VersionId": "v1"}
        api.head_object.return_value = {"ContentLength": len(PNG), "Metadata": {"sha256": hashlib.sha256(PNG).hexdigest()}}
        api.get_object.return_value = {"ContentLength": len(PNG), "Body": io.BytesIO(PNG)}
        with patch.dict(os.environ, {"EDITORIAL_MEDIA_BACKEND": "minio"}), patch("infrastructure.media.s3.client", return_value=api), patch("infrastructure.media.s3.bucket", return_value="private-media"), patch("infrastructure.images.sdcpp.render_png", new_callable=AsyncMock, return_value=PNG):
            response = await self.client.post(url, headers=self.auth)
            self.assertEqual(response.status_code, 201, response.text)
            scene_id, reference = self.store.image_asset(self.tenant, self.run_id, 1, True)
            self.assertEqual(reference["backend"], "minio")
            self.assertFalse(list(Path(self.media.name).rglob("*.png")))
            self.assertEqual((await self.client.get(url, headers=self.auth)).content, PNG)
            self.assertNotIn("bucket", response.text)
        # The old local backend remains the default, on another scene.
        with patch("infrastructure.images.sdcpp.render_png", new_callable=AsyncMock, return_value=PNG):
            local_url = f"/editorial/runs/{self.run_id}/scenes/2/image"
            self.assertEqual((await self.client.post(local_url, headers=self.auth)).status_code, 201)
            self.assertEqual((await self.client.get(local_url, headers=self.auth)).content, PNG)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT content->'storage'->>'backend' FROM po_entity WHERE tenant_id=%s AND entity_id=%s", (self.tenant, self.store._visual_id(scene_id))).fetchone()[0], "minio")

    async def test_production_media_reference_has_audit_outbox_and_no_cross_tenant_write(self):
        await self.approve()
        asset_id = uuid4()
        reference = {"backend": "minio", "kind": "video", "size": 42}
        self.store.record_media(self.tenant, self.actor, self.run_id, asset_id, reference)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT content->>'type' FROM po_entity WHERE tenant_id=%s AND entity_id=%s", (self.tenant, asset_id)).fetchone()[0], "production_media")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM po_audit a JOIN po_outbox o USING(event_id) WHERE a.tenant_id=%s AND a.entity_id=%s", (self.tenant, asset_id)).fetchone()[0], 1)
        from editorial.store import RunMissing
        with self.assertRaises(RunMissing):
            self.store.record_media(uuid4(), self.actor, self.run_id, uuid4(), reference)

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
        with patch("infrastructure.images.sdcpp.render_png", new_callable=AsyncMock, return_value=PNG) as render:
            response = await self.client.post(path, headers=self.auth)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(render.await_count, 1)
        self.assertEqual(response.json()["status"], "ready")
        download = await self.client.get(path, headers=self.auth)
        self.assertEqual(download.content, PNG)
        self.assertEqual(download.headers['cache-control'], 'private, no-store')
        self.assertEqual(download.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(download.headers['content-security-policy'], "default-src 'none'")
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
        with patch("infrastructure.images.sdcpp.render_png", new_callable=AsyncMock,
                   side_effect=ImageUnavailable()):
            response = await self.client.post(url, headers=self.auth)
        self.assertEqual(response.status_code, 502)
        plan = (await self.client.get(f"/editorial/runs/{self.run_id}/visuals",
                                     headers=self.auth)).json()
        self.assertEqual(plan["scenes"][0]["image_status"], "failed")
        self.assertEqual((await self.client.post(url, headers=self.auth)).status_code, 409)

    async def test_receipts_three_images_readonly_verification_and_tamper(self):
        from test_image_receipts import sample_scene
        png = sample_scene()[1]
        await self.approve()
        base = f"/editorial/runs/{self.run_id}"
        with patch("infrastructure.images.sdcpp.render_png", new_callable=AsyncMock, return_value=png) as render:
            for i in range(1, 4):
                response = await self.client.post(base + f"/scenes/{i}/image", headers=self.auth)
                self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(render.await_count, 3)
        counts_before = self.store.image_audit_counts(self.tenant, self.run_id)
        response = await self.client.get(base + "/visuals/verification", headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        report = response.json()
        self.assertTrue(report["technical_passed"], report)
        self.assertTrue(report["duplicate_image_digests"])
        self.assertFalse(report["gpu_verified"])
        self.assertTrue(report["human_visual_review_required"])
        self.assertEqual(self.store.image_audit_counts(self.tenant, self.run_id), counts_before)
        self.assertEqual(list(counts_before.values()), [2, 2, 2])
        plan = self.store.visual_plan(self.tenant, self.run_id)
        self.assertNotIn("character_references", plan["scenes"][0]["generation"]["provenance"])
        self.assertIsNone(plan["scenes"][0]["generation"]["provenance"]["seed"])
        run = self.store.get(self.tenant, self.run_id)
        path = Path(self.media.name) / str(self.tenant) / str(self.run_id) / (run["scene_ids"][0] + ".png")
        path.write_bytes(png + b"tampered")
        changed = (await self.client.get(base + "/visuals/verification", headers=self.auth)).json()
        self.assertFalse(changed["technical_passed"])
        self.assertIn("image_digest_mismatch_or_missing", changed["scenes"][0]["reasons"])
        self.assertEqual((await self.client.get(base + "/visuals/verification")).status_code, 401)
        with patch.dict(os.environ, {"EDITORIAL_TENANT_ID": str(uuid4())}):
            self.assertEqual((await self.client.get(base + "/visuals/verification", headers=self.auth)).status_code, 404)

    async def test_timeout_is_uncertain_and_does_not_repeat_provider_call(self):
        await self.approve()
        url = f"/editorial/runs/{self.run_id}/scenes/1/image"
        with patch("infrastructure.images.sdcpp.render_png", new_callable=AsyncMock,
                   side_effect=ImageUnavailable("image_provider_timeout")) as render:
            self.assertEqual((await self.client.post(url, headers=self.auth)).status_code, 504)
            self.assertEqual((await self.client.post(url, headers=self.auth)).status_code, 409)
        self.assertEqual(render.await_count, 1)
        generation = self.store.visual_plan(self.tenant, self.run_id)["scenes"][0]["generation"]
        self.assertTrue(generation["outcome_uncertain"])
        self.assertEqual(generation["error_code"], "image_provider_timeout")
        self.assertGreaterEqual(generation["duration_seconds"], 0)

    async def test_ambiguous_database_acknowledgement_preserves_private_png(self):
        import psycopg
        await self.approve()
        url = f"/editorial/runs/{self.run_id}/scenes/1/image"
        with patch("infrastructure.images.sdcpp.render_png", new_callable=AsyncMock, return_value=PNG), \
             patch("infrastructure.persistence.media_repository.PostgresMediaRepository.finish_image", side_effect=psycopg.OperationalError()):
            self.assertEqual((await self.client.post(url, headers=self.auth)).status_code, 503)
        run = self.store.get(self.tenant, self.run_id)
        self.assertEqual(load_png(self.tenant, self.run_id, UUID(run["scene_ids"][0])), PNG)
        self.assertEqual((await self.client.post(url, headers=self.auth)).status_code, 409)

    async def test_reservation_rejects_a_stale_prompt_or_scene_identity(self):
        from editorial.store import RunConflict
        await self.approve()
        plan = self.store.visual_plan(self.tenant, self.run_id)
        for prompt, scene_id in [("stale prompt", UUID(plan["scenes"][0]["scene_id"])),
                                 (plan["scenes"][0]["prompt"], uuid4())]:
            with self.assertRaises(RunConflict):
                self.store.begin_image(self.tenant, self.actor, self.run_id, 1, prompt, scene_id)
        self.assertEqual(self.store.visual_plan(self.tenant, self.run_id)["scenes"][0]["image_status"], "not_generated")

    async def test_catalog_keeps_http_envelope_and_authentication(self):
        base = f'/editorial/runs/{self.run_id}/media'
        self.assertEqual((await self.client.get(base)).status_code, 401)
        response = await self.client.get(base, headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'run_id': str(self.run_id), 'media': []})

    async def test_concurrent_reservations_create_one_audited_asset(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from editorial.store import RunConflict
        await self.approve()
        scene = self.store.visual_plan(self.tenant, self.run_id)['scenes'][0]
        barrier = Barrier(2)
        def reserve():
            barrier.wait(timeout=5)
            try:
                return self.store.begin_image(self.tenant, self.actor, self.run_id, 1,
                                              scene['prompt'], UUID(scene['scene_id']))
            except RunConflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(reserve) for _ in range(2)]
            results = [future.result(timeout=10) for future in futures]
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(list(self.store.image_audit_counts(self.tenant, self.run_id).values()), [1, 0, 0])

    async def test_restart_cannot_finalize_an_old_completed_reservation(self):
        from editorial.store import RunConflict
        await self.approve()
        scene = self.store.visual_plan(self.tenant, self.run_id)['scenes'][0]
        scene_id, _ = self.store.begin_image(self.tenant, self.actor, self.run_id, 1,
                                            scene['prompt'], UUID(scene['scene_id']))
        self.store.finish_image(self.tenant, self.actor, self.run_id, scene_id, width=1, height=1)
        restarted = PostgresStore(self.store.database_url)
        with self.assertRaises(RunConflict):
            restarted.finish_image(self.tenant, self.actor, self.run_id, scene_id, width=512, height=512)
        self.assertEqual(restarted.visual_plan(self.tenant, self.run_id)['scenes'][0]['generation']['width'], 1)
        self.assertEqual(list(restarted.image_audit_counts(self.tenant, self.run_id).values()), [2, 0, 0])

    async def test_finalization_waits_for_approval_transaction_then_rechecks(self):
        import time
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from psycopg.types.json import Jsonb
        from editorial.store import RunConflict
        await self.approve()
        scene = self.store.visual_plan(self.tenant, self.run_id)['scenes'][0]
        scene_id, _ = self.store.begin_image(self.tenant, self.actor, self.run_id, 1,
                                            scene['prompt'], UUID(scene['scene_id']))
        ready = Event()
        pid = []
        backend = self.store.media_repository()
        original_connect = backend.connect
        def connect():
            conn = original_connect()
            pid.append(conn.info.backend_pid)
            ready.set()
            return conn
        backend.connect = connect
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.store.connect() as conn:
                row = conn.execute("SELECT content FROM po_entity WHERE tenant_id=%s AND entity_id=%s FOR UPDATE",
                                   (self.tenant, self.run_id)).fetchone()
                future = pool.submit(backend.finish_image, self.tenant, self.actor, self.run_id,
                                     scene_id, width=1, height=1)
                self.assertTrue(ready.wait(timeout=5))
                waiting = False
                until = time.monotonic() + 3
                while time.monotonic() < until:
                    state = conn.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid[0],)).fetchone()
                    if state and state[0] == 'Lock':
                        waiting = True
                        break
                    if future.done():
                        break
                    time.sleep(0.01)
                # Snapshot content is synthetic test data; invalidate approval while holding its lock.
                content = row[0]
                content['status'] = 'rejected'
                conn.execute("UPDATE po_entity SET content=%s WHERE tenant_id=%s AND entity_id=%s",
                             (Jsonb(content), self.tenant, self.run_id))
            self.assertTrue(waiting, 'Finalization must lock the current approval before completing the asset')
            with self.assertRaises(RunConflict):
                future.result(timeout=5)


if __name__ == "__main__":
    unittest.main()

