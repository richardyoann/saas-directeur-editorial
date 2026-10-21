"""Regression cases discovered during the 2026-10-15 review; no real DB/model."""
import asyncio
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx

from apps.api.main import app
from apps.api.request_limits import (MAX_REQUEST_BYTES, MAX_JSON_DEPTH,
                                     JSONTooDeep, RequestLimits, load_bounded_json)
from apps.api.studio import failures, sessions
from editorial.api import get_store
from editorial.visuals import ImagePromptTooLong, ImageUnavailable, image_gate, render_png


class JSONDepthTests(unittest.TestCase):
    def test_exact_container_depth_boundary(self):
        raw = '[' * MAX_JSON_DEPTH + '0' + ']' * MAX_JSON_DEPTH
        self.assertIsInstance(load_bounded_json(raw), list)
        with self.assertRaises(JSONTooDeep):
            load_bounded_json('[' + raw + ']')

    def test_non_recursive_decoder_result_is_still_bounded(self):
        value = 0
        for _ in range(15000):
            value = [value]
        with patch('apps.api.request_limits.json.loads', return_value=value):
            with self.assertRaises(JSONTooDeep):
                load_bounded_json(b'[]')

    def test_object_depth_and_brackets_inside_strings(self):
        self.assertEqual(load_bounded_json('{"text":"[[[\\\"}]]"}'),
                         {"text": '[[["}]]'})
        raw = '{"x":' * (MAX_JSON_DEPTH + 1) + '0' + '}' * (MAX_JSON_DEPTH + 1)
        with self.assertRaises(JSONTooDeep):
            load_bounded_json(raw)


class RequestLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_chunked_body_rejected_before_app_and_remaining_chunks(self):
        called, consumed, sent = [], [], []

        async def application(*args):
            called.append(True)

        async def receive():
            consumed.append(True)
            return {"type": "http.request", "body": b"x" * MAX_REQUEST_BYTES,
                    "more_body": True}

        async def send(event):
            sent.append(event)

        await RequestLimits(application)({"type": "http", "method": "POST"}, receive, send)
        self.assertEqual(called, [])
        self.assertEqual(len(consumed), 2)
        self.assertEqual(sent[0]["status"], 413)

    async def test_small_chunked_body_replayed_exactly_once(self):
        chunks = iter([{"type": "http.request", "body": b"ab", "more_body": True},
                       {"type": "http.request", "body": b"cd", "more_body": False}])
        observed = []

        async def receive():
            return next(chunks)

        async def application(scope, receive, send):
            observed.append(await receive())

        await RequestLimits(application)({"type": "http", "method": "POST"}, receive, None)
        self.assertEqual(observed, [{"type": "http.request", "body": b"abcd", "more_body": False}])

    async def test_slow_body_times_out_before_application(self):
        sent = []

        async def receive():
            await asyncio.sleep(0.05)

        async def application(*args):
            self.fail("Application called for a timed-out request")

        async def send(event):
            sent.append(event)

        with patch("apps.api.request_limits.REQUEST_BODY_TIMEOUT", 0.001):
            await RequestLimits(application)({"type": "http", "method": "POST"}, receive, send)
        self.assertEqual(sent[0]["status"], 408)


class StudioMalformedInputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sessions.clear()
        failures.clear()
        env = patch.dict(os.environ, {
            "EDITORIAL_WEB_PASSWORD": "w" * 48, "EDITORIAL_API_TOKEN": "t" * 48,
            "EDITORIAL_TENANT_ID": str(uuid4()), "EDITORIAL_ACTOR_ID": str(uuid4())})
        env.start()
        self.addCleanup(env.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                        base_url="http://localhost")
        self.addAsyncCleanup(self.client.aclose)

    async def test_surrogate_password_returns_422_not_500(self):
        response = await self.client.post("/studio/session", content=b'{"password":"\\ud800"}',
                                          headers={"Origin": "http://localhost"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(sessions, {})

    async def test_deep_studio_json_returns_422(self):
        raw = b'{"password":' + b'[' * 15000 + b'0' + b']' * 15000 + b'}'
        response = await self.client.post("/studio/session", content=raw,
                                          headers={"Origin": "http://localhost"})
        self.assertEqual(response.status_code, 422)

    async def test_oversized_api_body_rejected_without_credentials(self):
        response = await self.client.post("/editorial/runs", content=b"x" * (MAX_REQUEST_BYTES + 1))
        self.assertEqual(response.status_code, 413)

    async def test_deep_api_json_returns_422_before_authentication(self):
        response = await self.client.post("/editorial/runs", content=b'[' * 15000 + b'0' + b']' * 15000,
                                          headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)

    async def test_non_ascii_csrf_is_denied_not_500(self):
        response = await self.client.post("/studio/session", json={"password": "w" * 48},
                                          headers={"Origin": "http://localhost"})
        self.assertEqual(response.status_code, 200)
        response = await self.client.post("/studio/logout", headers=[
            (b"Origin", b"http://localhost"), (b"X-CSRF-Token", b"\xc3\xa9")])
        self.assertEqual(response.status_code, 403)

    async def test_unicode_configured_password_can_sign_in(self):
        with patch.dict(os.environ, {"EDITORIAL_WEB_PASSWORD": "é" * 48}):
            response = await self.client.post("/studio/session", json={"password": "é" * 48},
                                              headers={"Origin": "http://localhost"})
        self.assertEqual(response.status_code, 200)


class ImageLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_wall_timeout_closes_stream_without_retry(self):
        class Stream(httpx.AsyncByteStream):
            closed = False

            async def __aiter__(self):
                await asyncio.sleep(1)
                yield b"{}"

            async def aclose(self):
                self.closed = True

        stream, calls = Stream(), []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, stream=stream)

        real_timeout = asyncio.timeout
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with patch("editorial.visuals.asyncio.timeout", side_effect=lambda _: real_timeout(0.01)):
                with self.assertRaises(ImageUnavailable) as caught:
                    await render_png(client, "http://127.0.0.1:8080", "scene")
        self.assertEqual(caught.exception.code, "image_provider_timeout")
        self.assertEqual(len(calls), 1)
        self.assertTrue(stream.closed)

    async def test_oversized_stream_stops_before_end(self):
        class Stream(httpx.AsyncByteStream):
            consumed = 0
            closed = False

            async def __aiter__(self):
                for _ in range(20):
                    self.consumed += 1
                    yield b"x" * (1024 * 1024)

            async def aclose(self):
                self.closed = True

        stream = Stream()
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=stream))) as client:
            with self.assertRaises(ImageUnavailable):
                await render_png(client, "http://127.0.0.1:8080", "scene")
        self.assertLess(stream.consumed, 20)
        self.assertTrue(stream.closed)

    async def test_image_redirect_is_refused(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={"Location": "https://example.com"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            with self.assertRaises(ImageUnavailable):
                await render_png(client, "http://127.0.0.1:8080", "scene")
        self.assertEqual(len(requests), 1)

    async def test_long_prompt_returns_422_and_releases_gate_before_reservation(self):
        class Store:
            def media_repository(self):
                return self

            def visual_plan(self, *args):
                raise ImagePromptTooLong()

            def begin_image(self, *args):
                raise AssertionError("No image reservation should be written")

        app.dependency_overrides[get_store] = lambda: Store()
        self.addCleanup(app.dependency_overrides.clear)
        with patch.dict(os.environ, {
            "EDITORIAL_API_TOKEN": "t" * 48, "EDITORIAL_TENANT_ID": str(uuid4()),
            "EDITORIAL_ACTOR_ID": str(uuid4()), "IMAGE_BASE_URL": "http://127.0.0.1:8080",
            "EDITORIAL_MEDIA_ROOT": "/tmp/unused-qa-media"}):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                          base_url="http://localhost") as client:
                root = "/editorial/runs/" + str(uuid4())
                for path, method in ((root + "/visuals", "GET"),
                                     (root + "/scenes/1/image", "POST")):
                    response = await client.request(method, path,
                                                     headers={"Authorization": "Bearer " + "t" * 48})
                    self.assertEqual(response.status_code, 422)
        self.assertTrue(image_gate.acquire(blocking=False))
        image_gate.release()
