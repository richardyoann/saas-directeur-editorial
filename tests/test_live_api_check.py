import unittest
import httpx
from uuid import uuid4
from scripts.live_api_check import check


class LiveContractTests(unittest.TestCase):
    def client(self, fail=None):
        editorial_posts = [0]
        def handler(request):
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "broken" if fail == "health" else "ok"})
            if request.content == b'{"prompt":" "}':
                return httpx.Response(200 if fail == "validation" else 422)
            if fail == "timeout":
                raise httpx.ReadTimeout("secret endpoint", request=request)
            if request.url.path == "/editorial/runs":
                if "Authorization" not in request.headers:
                    return httpx.Response(401)
                editorial_posts[0] += 1
                return httpx.Response(201 if editorial_posts[0] == 1 else 200, json={"id": "11111111-1111-4111-8111-111111111111",
                    "status": "failed" if fail == "editorial" else "waiting_validation", "requires_human_validation": True,
                    "steps": [{"name": "analysis"}, {"name": "storyboard"}]})
            if request.url.path == "/editorial/runs/11111111-1111-4111-8111-111111111111":
                return httpx.Response(200, json={"status": "waiting_validation"})
            if request.url.path.endswith("/history"):
                step = {"error_code": None, "response_metadata": {"finish_reason": "stop"}}
                return httpx.Response(200, json={"steps": [step, step]})
            return httpx.Response(200, json={"status": "success", "provider": "llama.cpp",
                "response": "" if fail == "empty" else "Bretagne",
                "finish_reason": None if fail == "missing_finish" else ("length" if fail == "truncated" else "stop"),
                "truncated": fail == "truncated"})
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_complete_response(self):
        self.assertEqual(check("http://127.0.0.1:8000", self.client())["real_generation"], "passed")

    def test_real_editorial_workflow(self):
        result = check("http://127.0.0.1:8000", self.client(),
                       editorial_token="x" * 32, idempotency_key=uuid4())
        self.assertEqual(result["real_editorial_workflow"], "passed")
        self.assertEqual(result["persistence"], "passed")
        self.assertEqual(result["idempotency"], "passed")

    def test_editorial_failure_blocks_delivery(self):
        with self.assertRaises(ValueError):
            check("http://127.0.0.1:8000", self.client("editorial"),
                  editorial_token="x" * 32, idempotency_key=uuid4())

    def test_editorial_credentials_are_atomic(self):
        with self.assertRaises(ValueError):
            check("http://127.0.0.1:8000", self.client(), editorial_token="x" * 32)

    def test_failures_block_delivery(self):
        for fail in ("health", "validation", "empty", "truncated", "timeout", "missing_finish"):
            with self.subTest(fail=fail), self.assertRaises((ValueError, httpx.HTTPError)):
                check("http://127.0.0.1:8000", self.client(fail))

    def test_remote_and_credential_urls_rejected(self):
        for url in ("http://example.org", "http://user:secret@localhost", "http://localhost/path", "https://localhost"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                check(url, self.client())
