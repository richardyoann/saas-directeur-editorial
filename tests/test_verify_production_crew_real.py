"""Offline tests of real-Qwen diagnostic: no actual network or PostgreSQL."""
import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from scripts.verify_production_crew_real import private_url, synthetic_source, verify


class CrewLiveVerificationUnitTests(unittest.IsolatedAsyncioTestCase):
    def test_private_url_rejects_external_secrets_and_paths(self):
        for raw in ("https://public.example:8080", "http://8.8.8.8:8080",
                    "http://169.254.169.254:80", "http://admin:secret@127.0.0.1:8080",
                    "http://0.0.0.0:8080", "http://127.0.0.1:8080/v1",
                    "file:///etc/shadow", "http://localhost:bad", ""):
            with self.subTest(raw=raw):
                self.assertIsNone(private_url(raw))
        self.assertEqual(private_url("http://127.0.0.1:8080"),
                         "http://127.0.0.1:8080")
        self.assertEqual(private_url("http://172.22.0.1:8080"),
                         "http://172.22.0.1:8080")

    async def test_only_one_real_role_in_default_mode(self):
        seen = []
        sample = {"summary": "Le récit contient une accroche et une vraie conclusion.",
                  "directions": ["Maintenir la tension narrative tout du long."],
                  "constraints_checked": ["Cinq scènes exactement, total 75 secondes."],
                  "handoff": "Transmettre une bible visuelle cohérente."}
        def handler(request):
            seen.append(request)
            self.assertEqual(request.url.path, "/v1/chat/completions")
            return httpx.Response(200, json={
                "choices": [{"message": {"content": json.dumps(sample)},
                             "finish_reason": "stop"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            report = await verify(client, "http://127.0.0.1:8080")
        self.assertTrue(report["all_requested_steps_valid"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(report["steps"][0]["role"], "screenwriter")
        self.assertFalse(report["multimedia_checked"])
        self.assertFalse(report["human_approval"])
        self.assertNotIn("Gardienne", json.dumps(report))

    async def test_invalid_response_never_retries(self):
        attempts = []
        def handler(request):
            attempts.append(request)
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "{}"},
                             "finish_reason": "stop"}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            report = await verify(client, "http://127.0.0.1:8080", all_roles=True)
        self.assertFalse(report["all_requested_steps_valid"])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(report["steps"][0]["status"], "invalid_structured_output")

    async def test_denied_address_performs_no_http_request(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            report = await verify(client, "https://public.example:443", all_roles=True)
        self.assertEqual(requests, [])
        self.assertFalse(report["all_requested_steps_valid"])


if __name__ == "__main__":
    unittest.main()
