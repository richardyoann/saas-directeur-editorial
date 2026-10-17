"""No real network or data for the private Qwen diagnostic tests."""
import json
import unittest

import httpx

from scripts.verify_qwen_structured import private_model_url, verify


class QwenStructuredVerificationTests(unittest.IsolatedAsyncioTestCase):
    def test_public_and_credentials_in_url_are_blocked(self):
        for url in ("https://example.com:443", "http://model.test:8080",
                    "http://name:secret@127.0.0.1:8080",
                    "http://127.0.0.1:8080/other",
                    "file:///tmp", "http://localhost:bad", ""):
            with self.subTest(url=url):
                self.assertIsNone(private_model_url(url))
        self.assertEqual(private_model_url("http://127.0.0.1:8080"),
                         "http://127.0.0.1:8080")
        self.assertEqual(private_model_url("http://172.20.0.1:8080"),
                         "http://172.20.0.1:8080")

    async def test_health_only_does_not_generate_or_store_anything(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify(client, "http://localhost:8080")
        self.assertEqual(result, {"health": "ok", "analysis": "not_run",
                                  "storyboard": "not_run", "calls": 0})
        self.assertEqual([r.method for r in requests], ["GET"])

    async def test_invalid_structured_output_stops_without_retry(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(200)
            payload = json.loads(request.content)
            self.assertEqual(payload["response_format"]["type"], "json_object")
            self.assertNotIn("$defs", json.dumps(payload["response_format"]))
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "not-json"}, "finish_reason": "stop"}]
            })
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify(client, "http://127.0.0.1:8080", generate=True)
        self.assertEqual(result["analysis"], "invalid_schema_output")
        self.assertEqual(result["storyboard"], "not_run")
        self.assertEqual(result["calls"], 1)
        self.assertEqual([r.method for r in requests], ["GET", "POST"])

    async def test_truncated_output_blocks_storyboard_without_second_call(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(200)
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "{}"}, "finish_reason": "length"}]
            })
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await verify(client, "http://127.0.0.1:8080", generate=True)
        self.assertEqual(result["analysis"], "output_incomplete")
        self.assertEqual(result["calls"], 1)
        self.assertEqual(len(requests), 2)


if __name__ == "__main__":
    unittest.main()
