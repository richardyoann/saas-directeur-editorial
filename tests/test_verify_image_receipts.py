import unittest
from uuid import uuid4

import httpx

from scripts.verify_image_receipts import inspect_receipts


class ReceiptCliTests(unittest.TestCase):
    def test_only_authenticated_get_and_no_generation_even_if_provider_claims_gpu(self):
        run_id = uuid4()
        seen = []
        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"run_id": str(run_id), "technical_passed": True,
                                            "gpu_verified": True, "expected_scenes": 3,
                                            "scenes": [{"passed": True}] * 3})
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            report = inspect_receipts(client, "http://127.0.0.1:8000", "t" * 48, run_id, 3)
        self.assertTrue(report["technical_passed"])
        self.assertFalse(report["gpu_verified"])
        self.assertTrue(report["human_visual_review_required"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].method, "GET")
        self.assertEqual(seen[0].headers["authorization"], "Bearer " + "t" * 48)

    def test_unsafe_url_or_missing_token_never_contacts_server(self):
        def forbidden(request):
            self.fail("No HTTP expected")
        with httpx.Client(transport=httpx.MockTransport(forbidden)) as client:
            for url, token in [("https://example.org", "t" * 48), ("http://localhost", "")]:
                self.assertFalse(inspect_receipts(client, url, token, uuid4(), 3)["technical_passed"])

    def test_redirect_error_malformed_and_wrong_run_are_rejected(self):
        for response in [httpx.Response(302, headers={"Location": "https://example.org"}),
                         httpx.Response(503), httpx.Response(200, text="not JSON"),
                         httpx.Response(200, json={"run_id": str(uuid4()), "technical_passed": True, "scenes": []})]:
            with httpx.Client(transport=httpx.MockTransport(lambda request: response)) as client:
                self.assertFalse(inspect_receipts(client, "http://localhost", "t" * 48, uuid4(), 3)["technical_passed"])
