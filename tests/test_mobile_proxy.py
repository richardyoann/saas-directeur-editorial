"""Private HTTPS reverse-proxy behavior with trusted vs untrusted peers.

This exercises the same Uvicorn proxy-header interpreter used by the documented
single-worker setup, but never exposes a real listener.
"""
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from apps.api.main import app
from apps.api.studio import sessions, failures


class PrivateMobileProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sessions.clear()
        failures.clear()
        self.env = patch.dict(os.environ, {
            "EDITORIAL_WEB_PASSWORD": "w" * 48,
            "EDITORIAL_API_TOKEN": "t" * 48,
            "EDITORIAL_TENANT_ID": str(uuid4()),
            "EDITORIAL_ACTOR_ID": str(uuid4()),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.wrapper = ProxyHeadersMiddleware(app, trusted_hosts=["127.0.0.1"])
        self.remote = "https://arvor.example.ts.net"

    def headers(self, source="100.101.1.1", origin=True):
        h = {"X-Forwarded-Proto": "https", "X-Forwarded-For": source}
        if origin:
            h["Origin"] = self.remote
        return h

    async def client(self, peer="127.0.0.1"):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.wrapper, client=(peer, 55000)),
            base_url="http://arvor.example.ts.net",
        )

    async def test_https_forwarded_session_is_secure_and_origin_checked(self):
        async with await self.client() as client:
            no_session = await client.get("/studio/session", headers=self.headers())
            self.assertEqual(no_session.status_code, 200)
            self.assertFalse(no_session.json()["authenticated"])
            incorrect = await client.post(
                "/studio/session", json={"password": "w" * 48},
                headers=self.headers(origin=False),
            )
            self.assertEqual(incorrect.status_code, 403)
            response = await client.post(
                "/studio/session", json={"password": "w" * 48},
                headers=self.headers(),
            )
            self.assertEqual(response.status_code, 200)
            cookie = response.headers["set-cookie"].lower()
            for required in ("secure", "httponly", "samesite=strict"):
                self.assertIn(required, cookie)
            # ASGITransport connects to the local HTTP hop, so its cookie jar
            # correctly withholds a Secure cookie. Replay only the opaque cookie
            # pair to model the external browser's HTTPS request through the proxy.
            session_cookie = response.headers["set-cookie"].split(";", 1)[0]
            proxied = self.headers() | {"Cookie": session_cookie}
            self.assertTrue((await client.get(
                "/studio/session", headers=proxied)).json()["authenticated"])
            csrf = response.json()["csrf"]
            logout = await client.post("/studio/logout",
                headers=proxied | {"X-CSRF-Token": csrf})
            self.assertEqual(logout.status_code, 200)
            self.assertFalse((await client.get(
                "/studio/session", headers=proxied)).json()["authenticated"])

    async def test_bruteforce_is_per_forwarded_client_not_proxy(self):
        async with await self.client() as client:
            for _ in range(5):
                response = await client.post("/studio/session",
                    headers=self.headers("100.101.1.1"),
                    json={"password": "invalid"})
                self.assertEqual(response.status_code, 401)
            locked = await client.post("/studio/session",
                headers=self.headers("100.101.1.1"),
                json={"password": "w" * 48})
            self.assertEqual(locked.status_code, 429)
            separate = await client.post("/studio/session",
                headers=self.headers("100.101.1.2"),
                json={"password": "w" * 48})
            self.assertEqual(separate.status_code, 200)

    async def test_untrusted_forwarded_headers_cannot_force_https(self):
        async with await self.client(peer="192.0.2.44") as client:
            response = await client.get("/studio/session", headers=self.headers())
            self.assertEqual(response.status_code, 403)
            response = await client.post(
                "/studio/session", headers=self.headers(),
                json={"password": "w" * 48})
            self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
