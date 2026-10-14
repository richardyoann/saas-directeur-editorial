"""Pre-activation Studio checks: isolated fake HTTP, never user credentials."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from deploy_local import check_studio


class StudioClient:
    def __init__(self, broken=None):
        self.broken = broken
        self.authenticated = False
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        self.calls.append(("GET", url))
        if self.broken == "js" and url.endswith("/studio/assets/studio.js"):
            return httpx.Response(404)
        if url.endswith("/studio"):
            return httpx.Response(200, text="<html></html>",
                                  headers={"Content-Type": "text/html"})
        if "/studio/assets/" in url:
            return httpx.Response(200, text="valid asset")
        if url.endswith("/studio/session"):
            return httpx.Response(200, json={"authenticated": self.authenticated})
        if url.endswith("/studio/api/runs?limit=1"):
            return httpx.Response(200 if self.authenticated else 401,
                                  json={"runs": []})
        return httpx.Response(404)

    def post(self, url, json=None, headers=None):
        self.calls.append(("POST", url))
        if url.endswith("/studio/session"):
            if (not headers or headers.get("Origin") != "http://127.0.0.1:8000"
                    or json != {"password": "w" * 48}):
                return httpx.Response(403)
            self.authenticated = True
            return httpx.Response(200, json={"authenticated": True, "csrf": "c" * 40},
                                  headers={"Set-Cookie": "s=x; HttpOnly; SameSite=Strict"})
        if url.endswith("/studio/logout"):
            if headers != {"Origin": "http://127.0.0.1:8000", "X-CSRF-Token": "c" * 40}:
                return httpx.Response(403)
            if self.broken != "logout":
                self.authenticated = False
            return httpx.Response(200, json={"authenticated": False})
        return httpx.Response(404)


class StudioDeliverySmokeTests(unittest.TestCase):
    def test_complete_anonymous_login_listing_logout_contract(self):
        client = StudioClient()
        with patch("httpx.Client", return_value=client):
            check_studio("http://127.0.0.1:8000", "w" * 48)
        self.assertFalse(client.authenticated)
        self.assertEqual([x[0] for x in client.calls].count("POST"), 2)
        self.assertTrue(any(u.endswith("/studio/api/runs?limit=1") for _, u in client.calls))

    def test_missing_assets_and_non_invalidation_block_release(self):
        for failure in ("js", "logout"):
            with self.subTest(failure=failure):
                with patch("httpx.Client", return_value=StudioClient(failure)):
                    with self.assertRaises(RuntimeError):
                        check_studio("http://127.0.0.1:8000", "w" * 48)

    def test_missing_password_fails_before_any_http_request(self):
        with patch("httpx.Client") as mocked:
            with self.assertRaises(RuntimeError):
                check_studio("http://127.0.0.1:8000", "")
            mocked.assert_not_called()
