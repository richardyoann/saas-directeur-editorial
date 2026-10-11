import os
import unittest
from unittest.mock import patch

import httpx

from apps.api.main import app, get_llm_client


class GenerateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"LLM_BASE_URL": "http://llm.test:8081/"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(app.dependency_overrides.clear)
        self.requests = []
        self.handler = lambda request: httpx.Response(200, json={
            "model": "Qwen2.5-3B-Instruct",
            "choices": [{"message": {"content": "Une réponse éditoriale."}}],
            "usage": {"completion_tokens": 6},
        })

        def transport(request):
            self.requests.append(request)
            return self.handler(request)

        async def mock_client():
            async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
                yield client

        app.dependency_overrides[get_llm_client] = mock_client
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test")
        self.addAsyncCleanup(self.client.aclose)

    async def generate(self, **kwargs):
        return await self.client.post("/ai/generate", json={"prompt": "Bonjour", **kwargs})

    async def test_success_and_upstream_contract(self):
        import json
        response = await self.generate(max_tokens=32)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["response"], "Une réponse éditoriale.")
        self.assertEqual(data["model"], "Qwen2.5-3B-Instruct")
        self.assertEqual(data["provider"], "llama.cpp")
        self.assertEqual(data["usage"], {"completion_tokens": 6})
        self.assertGreaterEqual(data["duration_seconds"], 0)
        self.assertEqual(str(self.requests[0].url), "http://llm.test:8081/v1/chat/completions")
        self.assertEqual(json.loads(self.requests[0].content), {
            "messages": [{"role": "user", "content": "Bonjour"}],
            "max_tokens": 32, "stream": False,
        })

    async def test_finish_reason_and_truncation(self):
        for reason, truncated in (("stop", False), ("length", True), (None, False),
                                  ("content_filter", False)):
            self.handler = lambda request: httpx.Response(200, json={
                "choices": [{"message": {"content": "Texte"}, "finish_reason": reason}]
            })
            with self.subTest(reason=reason):
                response = await self.generate()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["finish_reason"], reason)
                self.assertEqual(response.json()["truncated"], truncated)
        self.handler = lambda request: httpx.Response(200, json={
            "choices": [{"message": {"content": "Texte"}, "finish_reason": 42}]
        })
        self.assertEqual((await self.generate()).status_code, 502)

    async def test_invalid_input(self):
        for body in ({}, {"prompt": ""}, {"prompt": "  \n"}, {"prompt": 42},
                     {"prompt": "OK", "max_tokens": 0}, {"prompt": "OK", "max_tokens": 2049}):
            with self.subTest(body=body):
                self.assertEqual((await self.client.post("/ai/generate", json=body)).status_code, 422)
        self.assertEqual(self.requests, [])

    async def test_missing_or_invalid_configuration(self):
        for value in ("", "file:///tmp/model", "http://llm:bad", "http://user:secret@llm"):
            with self.subTest(value=value), patch.dict(os.environ, {"LLM_BASE_URL": value}):
                response = await self.generate()
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("secret", response.text)
        self.assertEqual(self.requests, [])

    async def test_unavailable_and_upstream_http_failure(self):
        def unavailable(request):
            raise httpx.ConnectError("private upstream detail", request=request)
        self.handler = unavailable
        response = await self.generate()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("private", response.text)
        self.handler = lambda request: httpx.Response(503, text="private upstream detail")
        self.assertEqual((await self.generate()).status_code, 502)

    async def test_timeout(self):
        for exception in (httpx.ConnectTimeout, httpx.ReadTimeout):
            def timeout(request):
                raise exception("timeout", request=request)
            self.handler = timeout
            with self.subTest(exception=exception):
                self.assertEqual((await self.generate()).status_code, 504)

    async def test_invalid_upstream_response(self):
        bodies = [{}, {"choices": []}, {"choices": [None]}, []]
        bodies += [{"choices": [{"message": {"content": value}}]}
                   for value in (None, "", "   ", 42, [])]
        for body in bodies:
            self.handler = lambda request: httpx.Response(200, json=body)
            with self.subTest(body=body):
                self.assertEqual((await self.generate()).status_code, 502)
        self.handler = lambda request: httpx.Response(200, text="invalid JSON")
        self.assertEqual((await self.generate()).status_code, 502)


if __name__ == "__main__":
    unittest.main()
