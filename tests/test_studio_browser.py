"""Chromium user journeys against disposable fake API, isolated from user data."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "w" * 48
TOKEN = "t" * 48
AUTH = {"Authorization": "Bearer " + TOKEN}


class StudioBrowserJourneys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.base = "http://localhost:" + str(port)
        env = os.environ.copy()
        env.update({
            "EDITORIAL_WEB_PASSWORD": PASSWORD,
            "EDITORIAL_API_TOKEN": TOKEN,
            "EDITORIAL_TENANT_ID": str(uuid4()),
            "EDITORIAL_ACTOR_ID": str(uuid4()),
            "PYTHONPATH": str(ROOT / "tests") + os.pathsep + str(ROOT),
        })
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "studio_browser_fixture:app",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "error"],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError("Browser fixture stopped before startup")
            try:
                with urlopen(cls.base + "/health", timeout=0.3) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError, ConnectionError):
                time.sleep(0.1)
        else:
            raise RuntimeError("Browser fixture did not start")
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(
                channel="chrome", headless=True, args=["--no-sandbox"])
        except Exception:
            cls.playwright.stop()
            cls.server.terminate()
            cls.server.wait(timeout=5)
            raise

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "browser"):
            cls.browser.close()
        if hasattr(cls, "playwright"):
            cls.playwright.stop()
        if hasattr(cls, "server"):
            cls.server.terminate()
            try:
                cls.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server.kill()
                cls.server.wait(timeout=5)

    def setUp(self):
        with httpx.Client(base_url=self.base) as client:
            self.assertEqual(client.post("/__fixture__/reset").status_code, 200)
        self.context = self.browser.new_context(
            viewport={"width": 1366, "height": 860}, locale="fr-FR")
        self.page = self.context.new_page()
        self.js_errors = []
        self.page.on("pageerror", lambda e: self.js_errors.append(str(e)))

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.js_errors, [], "Uncaught JavaScript exceptions")

    def sign_in(self):
        self.page.goto(self.base + "/studio")
        self.page.locator("#password").fill(PASSWORD)
        self.page.locator("#loginButton").click()
        self.page.locator("#app").wait_for(state="visible")
        self.page.locator("#runList").wait_for(state="visible")

    def create(self, topic="La ville d'Ys"):
        self.page.locator("#heroCreate").click()
        self.page.locator("#topic").fill(topic)
        self.page.locator("#submitNew").click()
        self.page.locator("#detail").wait_for(state="visible")
        self.page.locator("article.scene").first.wait_for(state="visible")
        self.assertEqual(self.page.locator("article.scene").count(), 3)
        self.assertEqual(self.page.locator("#storyTitle").inner_text(), topic)
        return self.page.evaluate("location.hash.slice(5)")

    def review(self, step, action="accept", comment="", corrected=None):
        self.page.locator('[data-tab="' + step + '"]').click()
        labels = {"accept": "Accepter", "reject": "Demander des changements", "revise": "Réviser"}
        self.page.locator("#panel .review-buttons").get_by_role(
            "button", name=labels[action]).click()
        self.page.locator("#reviewAction").select_option(action)
        if comment:
            self.page.locator("#reviewComment").fill(comment)
        if corrected is not None:
            self.page.locator("#revisionJson").fill(
                json.dumps(corrected, ensure_ascii=False))
        self.page.locator("#confirmReview").check()
        self.page.locator("#submitReview").click()
        self.page.locator("#reviewDialog").wait_for(state="hidden")

    def test_login_create_analysis_history_approve_logout(self):
        self.page.goto(self.base + "/studio")
        self.assertTrue(self.page.locator("#login").is_visible())
        self.assertTrue(self.page.locator("#app").is_hidden())
        self.page.locator("#password").fill("wrong" * 9)
        self.page.locator("#loginButton").click()
        self.page.locator("#loginError").wait_for(state="visible")
        self.assertIn("incorrect", self.page.locator("#loginError").inner_text())
        self.page.locator("#password").fill(PASSWORD)
        self.page.locator("#loginButton").click()
        self.page.locator("#empty").wait_for(state="visible")
        run_id = self.create()
        self.page.locator('[data-tab="analysis"]').click()
        self.assertIn("Vérifier les sources", self.page.locator("#panel").inner_text())
        self.page.locator('[data-tab="history"]').click()
        self.assertEqual(self.page.locator("#panel article.card").count(), 2)
        self.assertIn("Voir le prompt", self.page.locator("#panel").inner_text())
        self.review("analysis")
        self.review("storyboard")
        self.assertEqual(self.page.locator("#status").inner_text(), "Approuvé")
        self.assertTrue(self.page.locator("#decisionFoot").is_hidden())
        self.page.locator('[data-tab="reviews"]').click()
        self.assertEqual(self.page.locator("#panel .history-entry").count(), 2)
        self.page.locator("#logout").click()
        self.page.locator("#login").wait_for(state="visible")
        self.assertTrue(self.page.locator("#app").is_hidden())
        self.page.goto(self.base + "/studio#run/" + run_id)
        self.page.locator("#password").fill(PASSWORD)
        self.page.locator("#loginButton").click()
        self.page.locator("#storyTitle").wait_for(state="visible")
        self.assertEqual(self.page.locator("#storyTitle").inner_text(), "La ville d'Ys")

    def test_reject_revise_accept_and_invalid_json(self):
        self.sign_in()
        self.create("La forêt de Brocéliande")
        self.review("storyboard", "reject", "Améliorer la narration")
        self.assertEqual(self.page.locator("#status").inner_text(), "À retravailler")
        self.page.locator('[data-tab="storyboard"]').click()
        self.page.locator("#panel .review-buttons").get_by_role("button", name="Réviser").click()
        self.page.locator("#reviewComment").fill("Corriger le découpage")
        self.page.locator("#revisionJson").fill("{JSON invalide")
        self.page.locator("#confirmReview").check()
        self.page.locator("#submitReview").click()
        self.page.locator("#reviewError").wait_for(state="visible")
        self.assertTrue(self.page.locator("#reviewDialog").is_visible())
        self.assertIn("JSON", self.page.locator("#reviewError").inner_text())
        self.assertNotIn("editorial_studio_session",
                         self.page.evaluate("document.cookie"))
        revised = {
            "title": "Brocéliande — version éditée",
            "synopsis": "Récit révisé",
            "scenes": [
                {"title": "Scène " + str(i), "duration_seconds": 20,
                 "narration": "Le récit continue", "visual_description": "Forêt",
                 "characters": ["Merlin"], "landscape": "Brocéliande",
                 "colors": ["vert"], "shot": "Plan large", "emotion": "Mystère",
                 "sound": "Vent", "image_prompt": "Forêt enchantée"}
                for i in (1, 2, 3)
            ],
        }
        self.page.locator("#revisionJson").fill(
            json.dumps(revised, ensure_ascii=False))
        self.page.locator("#submitReview").click()
        self.page.locator("#reviewDialog").wait_for(state="hidden")
        self.assertEqual(self.page.locator("#storyTitle").inner_text(),
                         "Brocéliande — version éditée")
        self.review("storyboard")
        self.review("analysis")
        self.assertEqual(self.page.locator("#status").inner_text(), "Approuvé")
        self.page.locator('[data-tab="reviews"]').click()
        self.assertEqual(self.page.locator("#panel .history-entry").count(), 4)

    def test_pagination_search_navigation_and_mobile(self):
        with httpx.Client(base_url=self.base, headers=AUTH) as client:
            for i in range(23):
                response = client.post(
                    "/editorial/runs", headers={"Idempotency-Key": str(uuid4())},
                    json={"topic": "Histoire numéro " + str(i)})
                self.assertEqual(response.status_code, 200)
        self.sign_in()
        self.page.locator(".run-item").first.wait_for(state="visible")
        self.assertEqual(self.page.locator(".run-item").count(), 20)
        self.page.locator("#more").click()
        self.assertEqual(self.page.locator(".run-item").count(), 23)
        self.page.locator("#filter").fill("numéro 22")
        self.assertEqual(self.page.locator(".run-item").count(), 1)
        self.page.locator("#filter").fill("")
        self.page.locator(".run-item").first.click()
        self.page.locator("#detail").wait_for(state="visible")
        self.page.locator("#home").click()
        self.page.locator("#empty").wait_for(state="visible")
        self.page.go_back()
        self.page.locator("#detail").wait_for(state="visible")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertLessEqual(
            self.page.evaluate("document.documentElement.scrollWidth"),
            self.page.evaluate("window.innerWidth") + 1)
        self.page.locator("#menu").click()
        self.assertIn("open", self.page.locator("#sidebar").get_attribute("class"))
        self.page.locator("#home").click()
        self.assertTrue(self.page.locator("#empty").is_visible())

    def test_conflict_requires_refresh_without_automatic_replay(self):
        self.sign_in()
        self.create("L'Ankou")
        calls = []
        def conflict(route):
            calls.append(route.request.method)
            route.fulfill(
                status=409, content_type="application/json",
                body='{"detail":"conflict"}')
        pattern = "**/studio/api/runs/*/steps/*/review"
        self.page.route(pattern, conflict)
        self.page.locator("#panel .review-buttons").get_by_role("button", name="Accepter").click()
        self.page.locator("#confirmReview").check()
        self.page.locator("#submitReview").click()
        self.page.locator("#reviewDialog").wait_for(state="hidden")
        self.assertEqual(len(calls), 1)
        self.assertIn("Conflit", self.page.locator("#notice").inner_text())
        self.page.unroute(pattern)
        self.review("storyboard")
        self.assertEqual(self.page.locator("#status").inner_text(), "À valider")

    def test_generation_network_requires_explicit_retry(self):
        self.sign_in()
        requests = []
        def abort(route):
            requests.append(route.request.headers.get("idempotency-key"))
            route.abort("failed")
        pattern = "**/studio/api/runs"
        self.page.route(pattern, abort)
        self.page.locator("#heroCreate").click()
        self.page.locator("#topic").fill("Les korrigans")
        self.page.locator("#submitNew").click()
        self.page.locator("#newDialog").wait_for(state="hidden")
        self.assertEqual(len(requests), 1)
        self.page.unroute(pattern)
        self.page.locator("#heroCreate").click()
        self.assertEqual(self.page.locator("#topic").input_value(), "Les korrigans")
        self.page.locator("#submitNew").click()
        self.page.locator("#detail").wait_for(state="visible")
        self.assertEqual(self.page.locator("#storyTitle").inner_text(), "Les korrigans")
        with httpx.Client(base_url=self.base) as client:
            self.assertEqual(client.get("/__fixture__/counts").json()["generate"], 1)


if __name__ == "__main__":
    unittest.main()
