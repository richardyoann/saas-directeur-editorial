import unittest
import httpx
from scripts.live_api_check import check


class LiveContractTests(unittest.TestCase):
    def client(self, fail=None):
        def handler(request):
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "broken" if fail == "health" else "ok"})
            if request.content == b'{"prompt":" "}':
                return httpx.Response(200 if fail == "validation" else 422)
            if fail == "timeout":
                raise httpx.ReadTimeout("secret endpoint", request=request)
            return httpx.Response(200, json={"status": "success", "provider": "llama.cpp",
                "response": "" if fail == "empty" else "Bretagne",
                "finish_reason": "length" if fail == "truncated" else "stop",
                "truncated": fail == "truncated"})
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_complete_response(self):
        self.assertEqual(check("http://127.0.0.1:8000", self.client())["real_generation"], "passed")

    def test_failures_block_delivery(self):
        for fail in ("health", "validation", "empty", "truncated", "timeout"):
            with self.subTest(fail=fail), self.assertRaises((ValueError, httpx.HTTPError)):
                check("http://127.0.0.1:8000", self.client(fail))

    def test_remote_and_credential_urls_rejected(self):
        for url in ("http://example.org", "http://user:secret@localhost", "http://localhost/path", "https://localhost"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                check(url, self.client())
