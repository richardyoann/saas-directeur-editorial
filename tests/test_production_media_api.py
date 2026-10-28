"""HTTP contract for the voice/video routes: auth, errors, headers, no leaks."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx

from apps.api.main import app
from editorial.api import get_identity, get_store
from editorial.media.contracts import PersistenceUnavailable, RunConflict, RunMissing
from production.media_pipeline import ProductionMediaError


class FakeService:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    async def execute(self, identity, run_id):
        if self.error:
            raise self.error
        return self.result

    async def read(self, identity, run_id, media_id):
        if self.error:
            raise self.error
        return self.result

    async def plan(self, identity, run_id):
        if self.error:
            raise self.error
        return self.result


class ProductionMediaApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tenant, self.actor = uuid4(), uuid4()
        self.token = "t" * 32
        self.env = patch.dict(os.environ, {
            "EDITORIAL_API_TOKEN": self.token,
            "EDITORIAL_TENANT_ID": str(self.tenant),
            "EDITORIAL_ACTOR_ID": str(self.actor),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(app.dependency_overrides.clear)
        app.dependency_overrides[get_store] = lambda: object()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.headers = {"Authorization": "Bearer " + self.token}
        self.run_id = uuid4()

    def serve(self, **services):
        patches = []
        for name, value in services.items():
            patches.append(patch(f"apps.api.production_media.{name}",
                                 side_effect=lambda store, _value=value: _value))
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    async def test_routes_require_the_private_bearer_token(self):
        for method, path in (
            ("get", f"/editorial/runs/{self.run_id}/production-media"),
            ("post", f"/editorial/runs/{self.run_id}/voice"),
            ("post", f"/editorial/runs/{self.run_id}/video"),
            ("get", f"/editorial/runs/{self.run_id}/media/{uuid4()}/content"),
        ):
            with self.subTest(path=path):
                response = await getattr(self.client, method)(path)
                self.assertEqual(response.status_code, 401)
                other = await getattr(self.client, method)(
                    path, headers={"Authorization": "Bearer " + "x" * 32})
                self.assertEqual(other.status_code, 401)

    async def test_plan_returns_the_production_state(self):
        self.serve(build_media_stream=FakeService({"approved": True, "media": {}}))
        response = await self.client.get(
            f"/editorial/runs/{self.run_id}/production-media", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"approved": True, "media": {}})

    async def test_plan_missing_run_is_404_and_database_outage_is_503(self):
        self.serve(build_media_stream=FakeService(error=RunMissing()))
        response = await self.client.get(
            f"/editorial/runs/{self.run_id}/production-media", headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.serve(build_media_stream=FakeService(error=PersistenceUnavailable()))
        response = await self.client.get(
            f"/editorial/runs/{self.run_id}/production-media", headers=self.headers)
        self.assertEqual(response.status_code, 503)

    async def test_voice_conflict_and_error_translation(self):
        self.serve(build_voice_service=FakeService(error=RunConflict()))
        response = await self.client.post(
            f"/editorial/runs/{self.run_id}/voice", headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.serve(build_voice_service=FakeService(
            error=ProductionMediaError("media_capacity_busy")))
        response = await self.client.post(
            f"/editorial/runs/{self.run_id}/voice", headers=self.headers)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("retry-after"), "30")
        self.serve(build_voice_service=FakeService(
            error=ProductionMediaError("voice_provider_unconfigured")))
        response = await self.client.post(
            f"/editorial/runs/{self.run_id}/voice", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("piper", response.text.lower())

    async def test_video_success_and_render_failure(self):
        self.serve(build_video_service=FakeService({"kind": "video"}))
        response = await self.client.post(
            f"/editorial/runs/{self.run_id}/video", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.serve(build_video_service=FakeService(
            error=ProductionMediaError("video_render_failed")))
        response = await self.client.post(
            f"/editorial/runs/{self.run_id}/video", headers=self.headers)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("ffmpeg", response.text.lower())

    async def test_content_is_private_and_cleanup_runs_after_delivery(self):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "voice.wav"
        path.write_bytes(b"RIFF" + b"\x00" * 8)
        self.serve(build_media_stream=FakeService(
            {"kind": "voice", "path": path, "directory": directory}))
        response = await self.client.get(
            f"/editorial/runs/{self.run_id}/media/{uuid4()}/content",
            headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"RIFF" + b"\x00" * 8)
        self.assertEqual(response.headers["content-type"], "audio/wav")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertFalse(path.exists())

    async def test_download_sets_a_bounded_filename_per_kind(self):
        for kind, suffix in (("video", ".mp4"), ("subtitles", ".srt")):
            directory = tempfile.TemporaryDirectory()
            path = Path(directory.name) / ("media" + suffix)
            path.write_bytes(b"data")
            self.serve(build_media_stream=FakeService(
                {"kind": kind, "path": path, "directory": directory}))
            response = await self.client.get(
                f"/editorial/runs/{self.run_id}/media/{uuid4()}/content",
                params={"download": "1"}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            disposition = response.headers["content-disposition"]
            self.assertIn(str(self.run_id)[:8], disposition)
            self.assertTrue(disposition.endswith(f'{suffix}"'))

    async def test_unknown_media_kind_is_404_and_path_is_never_reflected(self):
        self.serve(build_media_stream=FakeService(
            error=ProductionMediaError("media_kind_invalid")))
        response = await self.client.get(
            f"/editorial/runs/{self.run_id}/media/{uuid4()}/content",
            headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.serve(build_media_stream=FakeService(error=RunMissing()))
        response = await self.client.get(
            f"/editorial/runs/{self.run_id}/media/{uuid4()}/content",
            headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("private", response.text)


if __name__ == "__main__":
    unittest.main()
