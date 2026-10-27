"""TCP-level contract tests against a disposable fake sd-server.

These tests use HTTP localhost and an in-memory PNG fixture; they never
execute a model, access the PC GPU, or write to the user's runtime.
"""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import unittest

import httpx

from editorial.visuals import image_prompt, render_png, ImageUnavailable
from infrastructure.images.sdcpp import image_timeout_seconds
from scripts.diagnose_image_runtime import inspect_models
from test_editorial import outputs


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


class LocalImageApi(BaseHTTPRequestHandler):
    generation_calls = []
    model_calls = 0

    def log_message(self, fmt, *args):
        # No prompts or HTTP bodies in CI logs.
        pass

    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            type(self).model_calls += 1
            return self.send_json(200, {"data": [
                {"id": "sd-cpp-local", "object": "model", "owned_by": "local"}
            ]})
        return self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/images/generations":
            return self.send_json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("content-length", "0"))
            if not 0 < length <= 25000:
                raise ValueError()
            body = json.loads(self.rfile.read(length))
        except (ValueError, TypeError, json.JSONDecodeError):
            return self.send_json(400, {"error": "invalid request"})
        if (body.get("n") != 1 or body.get("size") != "512x512"
                or body.get("output_format") != "png"
                or "response_format" in body or not body.get("prompt")):
            return self.send_json(422, {"error": "sd.cpp schema mismatch"})
        type(self).generation_calls.append(body["prompt"])
        self.send_json(200, {
            "created": 1792040000, "output_format": "png",
            "data": [{"b64_json": base64.b64encode(PNG).decode("ascii")}],
        })


class SDServerBridgeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        LocalImageApi.generation_calls = []
        LocalImageApi.model_calls = 0
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), LocalImageApi)
        cls.address = "http://127.0.0.1:" + str(cls.server.server_address[1])
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_preflight_lists_models_without_generating(self):
        with httpx.Client(trust_env=False) as client:
            result = inspect_models(client, self.address)
        self.assertTrue(result["ready"])
        self.assertEqual(result["model_count"], 1)
        self.assertEqual(LocalImageApi.generation_calls, [])
        self.assertFalse(inspect_models(client=None, base_url="https://example.org")["ready"])

    async def test_three_scene_prompts_use_one_character_appearance_over_tcp(self):
        storyboard = outputs()[1]
        storyboard["cast"] = [{
            "name": "Un marin", "appearance": "Manteau rouge et barbe grise",
            "role": "Guide", "personality": "Courageux",
        }]
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            pixels = [await render_png(client, self.address, image_prompt(
                {"storyboard": storyboard}, i)) for i in range(1, 4)]
        self.assertEqual(pixels, [PNG, PNG, PNG])
        self.assertEqual(len(LocalImageApi.generation_calls), 3)
        self.assertTrue(all(
            "Manteau rouge et barbe grise" in prompt
            for prompt in LocalImageApi.generation_calls
        ))

    async def test_unreachable_endpoint_fails_without_an_external_fallback(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(302, headers={
                    "Location": "https://public-service.example/v1/images/generations"
                })
            ),
            follow_redirects=False, trust_env=False,
        ) as client:
            with self.assertRaises(ImageUnavailable):
                await render_png(client, self.address, "Une légende")


class ImageTimeoutConfigurationTests(unittest.TestCase):
    def test_timeout_is_bounded_and_configurable(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(image_timeout_seconds(), 300)
        for raw, expected in (("240", 240), ("1", 30), ("9999", 600),
                              ("invalid", 300), ("", 300)):
            with self.subTest(raw=raw), patch.dict("os.environ",
                                                   {"ARVOR_IMAGE_TIMEOUT_SECONDS": raw}):
                self.assertEqual(image_timeout_seconds(), expected)


if __name__ == "__main__":
    unittest.main()
