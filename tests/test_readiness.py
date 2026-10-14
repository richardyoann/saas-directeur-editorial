"""Readiness never leaks provider or database credentials."""
import os
import unittest
from unittest.mock import patch

import httpx

from apps.api.main import app, get_llm_client, lifespan


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.addCleanup(app.dependency_overrides.clear)

    async def probe(self, db_ok, llm_status):
        def provider(request):
            self.assertEqual(request.url.path, "/health")
            return httpx.Response(llm_status)

        async def mock_llm():
            async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
                yield client

        app.dependency_overrides[get_llm_client] = mock_llm
        with patch.dict(os.environ, {"LLM_BASE_URL": "http://model.test"}), patch(
            "apps.api.main._database_ready", return_value=db_ok
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                return await client.get("/ready")

    async def test_readiness_requires_both_provider_and_database(self):
        self.assertEqual((await self.probe(True, 200)).json(), {"ready": True})
        for db, llm in ((False, 200), (True, 503), (False, 503)):
            with self.subTest(db=db, llm=llm):
                response = await self.probe(db, llm)
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"ready": False})

    async def test_missing_provider_configuration_is_not_ready(self):
        with patch.dict(os.environ, {"LLM_BASE_URL": ""}), patch(
            "apps.api.main._database_ready", return_value=True
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost"
            ) as client:
                response = await client.get("/ready")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {"ready": False})

    async def test_lifespan_reuses_clients_and_closes_them(self):
        async with lifespan(app):
            llm_client = app.state.llm_client
            internal = app.state.internal_client
            self.assertFalse(llm_client.is_closed)
            self.assertFalse(internal.is_closed)
            self.assertIs(app.state.llm_client, llm_client)
            self.assertIs(app.state.internal_client, internal)
        self.assertTrue(llm_client.is_closed)
        self.assertTrue(internal.is_closed)
        self.assertFalse(hasattr(app.state, "llm_client"))


if __name__ == "__main__":
    unittest.main()
