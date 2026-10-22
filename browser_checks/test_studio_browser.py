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
from playwright.sync_api import expect, sync_playwright

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
        self.page.locator("#panel .story-tile").first.wait_for(state="visible")
        self.assertEqual(self.page.locator("#panel .story-tile").count(), 3)
        self.assertEqual(self.page.locator("#storyTitle").inner_text(), topic)
        return self.page.evaluate("location.hash.slice(5)")

    def review(self, step, action="accept", comment=""):
        self.page.locator('[data-tab="' + step + '"]').click()
        labels = {"accept": "Accepter", "reject": "Demander des changements", "revise": "Réviser"}
        self.page.locator("#panel .review-buttons").get_by_role(
            "button", name=labels[action]).click()
        self.page.locator("#reviewAction").select_option(action)
        if comment:
            self.page.locator("#reviewComment").fill(comment)
        self.page.locator("#confirmReview").check()
        self.page.locator("#submitReview").click()
        self.page.locator("#reviewDialog").wait_for(state="hidden")

    def test_reference_journal_and_admin_navigation(self):
        self.sign_in()
        self.create("La lumière de Brocéliande")
        self.page.locator("#home").click()
        expect(self.page.locator("#count")).to_be_visible()
        self.page.locator("#journalNav").click()
        expect(self.page.locator("#journal")).to_be_visible()
        expect(self.page.locator("#journal .arvor-entry-main")).to_have_count(1)
        self.page.locator("#journal .arvor-entry-main").first.click()
        expect(self.page.locator("#journal .arvor-entry-details")).to_be_visible()
        expect(self.page.locator("#journal .arvor-trace")).not_to_have_count(0)
        self.page.locator("#conceptionNav").click()
        expect(self.page.locator("#conception")).to_be_visible()
        expect(self.page.locator("#arvorAdminTabs [role=tab]")).to_have_count(5)
        self.page.locator("#arvorAdminTabs").get_by_role("tab",name="Agenda").click()
        # No private GitHub token is injected into the browser test fixture.
        # The UI reports the missing integration instead of inventing events.
        expect(self.page.locator("#arvorAdminSurface")).to_be_visible()
        self.page.locator("#home").click()
        expect(self.page.locator("#library")).to_be_visible()
        expect(self.page.locator("#count")).to_be_visible()

    def test_admin_real_github_data_statuses_and_calendar_modes(self):
        self.sign_in()
        github_base = "https://github.com/richardyoann/saas-directeur-editorial"
        sha = "a" * 40
        overview = {
            "repository_url": github_base,
            "epics": [{"number": 93, "title": "Epic navigation", "state": "open",
                        "created_at": "2026-10-16T10:00:00Z"}],
            "issues": [{"number": 93, "title": "Epic navigation", "state": "open",
                        "created_at": "2026-10-16T10:00:00Z"}],
            "pull_requests": [{"number": 97, "title": "Nouvelle interface", "state": "closed",
                               "draft": False, "merged_at": "2026-10-16T11:00:00Z",
                               "created_at": "2026-10-16T09:00:00Z",
                               "updated_at": "2026-10-16T11:00:00Z",
                               "sha": sha, "merge_commit_sha": sha}],
            "deliveries": [{"id": 7, "sha": sha, "created_at": "2026-10-16T11:00:00Z",
                            "conclusion": "success", "status": "completed"}],
            "source_truncated": {"issues": False, "pull_requests": False,
                                 "deliveries": False},
        }
        commits = {"commits": [{"sha": sha, "message": "Correction de navigation",
                               "when": "2026-10-16T10:00:00Z"}], "partial": False}
        ci = {"runs": [{"id": 10, "sha": sha, "event": "push",
                        "status": "completed", "conclusion": "failure",
                        "created_at": "2026-10-16T12:00:00Z"}], "partial": False}

        def mocked(route, data):
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(data))

        self.page.route("**/studio/api/conception", lambda route: mocked(route, overview))
        self.page.route("**/studio/api/conception/commits?*", lambda route: mocked(route, commits))
        self.page.route("**/studio/api/conception/ci?*", lambda route: mocked(route, ci))
        self.page.locator("#conceptionNav").click()
        expect(self.page.locator("#arvorAdminSurface .arvor-stat")).to_have_count(4)
        self.page.locator("#arvorAdminTabs").get_by_role("tab", name="Pull requests").click()
        expect(self.page.locator("#arvorAdminSurface")).to_contain_text("CI KO")
        self.page.locator("#arvorAdminTabs").get_by_role("tab", name="Commits").click()
        expect(self.page.locator("#arvorAdminSurface")).to_contain_text("Correction de navigation")
        self.page.locator("#arvorAdminTabs").get_by_role("tab", name="Agenda").click()
        expect(self.page.locator(".arvor-calendar-cell")).not_to_have_count(0)
        self.page.get_by_role("button", name="Semaine").click()
        expect(self.page.locator(".arvor-calendar-cell")).to_have_count(7)
        self.page.get_by_role("button", name="Jour", exact=True).click()
        expect(self.page.locator(".arvor-calendar-cell")).to_have_count(1)

    def test_visual_character_to_private_image_after_approval(self):
        self.sign_in()
        run_id = self.create("Le marin d'Ys")
        self.page.locator('[data-tab="visuals"]').click()
        expect(self.page.locator("#panel .visual-card")).to_have_count(3)
        self.assertIn("Manteau de laine rouge", self.page.locator("#panel").inner_text())
        first = self.page.locator("#panel .visual-card").first
        self.assertTrue(first.get_by_role("button", name="Générer cette image").is_disabled())
        first.locator("summary").click()
        self.assertIn("Manteau de laine rouge", first.locator("details p").inner_text())
        self.review("analysis")
        self.review("storyboard")
        self.page.locator('[data-tab="visuals"]').click()
        first = self.page.locator("#panel .visual-card").first
        button = first.get_by_role("button", name="Générer cette image")
        expect(button).to_be_enabled()
        button.click()
        expect(first.locator("img.image-preview")).to_have_count(1)
        src = first.locator("img.image-preview").get_attribute("src")
        self.assertEqual(src, f"/studio/api/runs/{run_id}/scenes/1/image")
        expect(first.locator("img.image-preview")).to_have_js_property("complete", True)
        with httpx.Client(base_url=self.base) as unauth:
            self.assertEqual(unauth.get(src).status_code, 401)
        self.assertEqual(self.page.locator("#panel .visual-card").count(), 3)
        self.assertEqual(self.page.locator("#panel .visual-card img").count(), 1)
        expect(first).to_contain_text("Durée : 1.25 s")
        self.page.get_by_role("button", name="Vérifier les images et leur historique").click()
        expect(self.page.locator("#panel")).to_contain_text("Contrôle incomplet")
        for number in (2, 3):
            self.page.locator("#panel .visual-card").nth(number - 1).get_by_role(
                "button", name="Générer cette image").click()
            expect(self.page.locator("#panel .visual-card img")).to_have_count(number)
        self.page.get_by_role("button", name="Vérifier les images et leur historique").click()
        expect(self.page.locator("#panel")).to_contain_text("Intégrité et historique vérifiés.")
        expect(self.page.locator("#panel")).to_contain_text("GPU et VRAM non mesurés.")

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
        self.page.locator("#library").wait_for(state="visible")
        run_id = self.create()
        self.page.locator('[data-tab="analysis"]').click()
        self.assertIn("Vérifier les sources", self.page.locator("#panel").inner_text())
        self.page.locator('[data-tab="history"]').click()
        expect(self.page.locator("#panel article.card")).to_have_count(2)
        self.assertIn("Voir le prompt", self.page.locator("#panel").inner_text())
        self.review("analysis")
        self.review("storyboard")
        self.assertEqual(self.page.locator("#status").inner_text(), "Approuvé")
        self.assertTrue(self.page.locator("#decisionFoot").is_hidden())
        self.page.locator('[data-tab="reviews"]').click()
        expect(self.page.locator("#panel .history-entry")).to_have_count(2)
        self.page.locator("#logout").click()
        self.page.locator("#login").wait_for(state="visible")
        self.assertTrue(self.page.locator("#app").is_hidden())
        self.page.goto(self.base + "/studio#run/" + run_id)
        self.page.locator("#password").fill(PASSWORD)
        self.page.locator("#loginButton").click()
        self.page.locator("#storyTitle").wait_for(state="visible")
        self.assertEqual(self.page.locator("#storyTitle").inner_text(), "La ville d'Ys")

    def test_reject_guided_revision_duration_validation_and_approval(self):
        self.sign_in()
        self.create("La forêt de Brocéliande")
        self.review("storyboard", "reject", "Améliorer la narration")
        self.assertEqual(self.page.locator("#status").inner_text(), "À retravailler")
        self.page.locator('[data-tab="storyboard"]').click()
        self.page.locator("#panel .review-buttons").get_by_role("button", name="Réviser").click()
        self.page.locator("#reviewComment").fill("Correction du découpage")
        self.assertEqual(self.page.locator("#editFields fieldset.edit-scene").count(), 3)
        self.page.locator("#edit-title").fill("Brocéliande — version éditée")
        self.page.locator("#edit-synopsis").fill("Récit révisé")
        self.page.locator("#edit-scene-0-narration").fill("Narration humaine de la forêt")
        self.page.locator("#edit-scene-0-characters").fill("Merlin\nViviane")
        self.page.locator("#edit-scene-0-colors").fill("vert\nbleu")
        self.page.locator("#edit-scene-0-duration_seconds").fill("21")
        self.page.locator("#confirmReview").check()
        self.page.locator("#submitReview").click()
        self.page.locator("#reviewError").wait_for(state="visible")
        self.assertIn("durée totale", self.page.locator("#reviewError").inner_text())
        self.assertTrue(self.page.locator("#reviewDialog").is_visible())
        self.assertNotIn("editorial_studio_session", self.page.evaluate("document.cookie"))
        self.page.locator("#edit-scene-0-duration_seconds").fill("20")
        self.page.locator("#submitReview").click()
        self.page.locator("#reviewDialog").wait_for(state="hidden")
        self.assertEqual(self.page.locator("#storyTitle").inner_text(), "Brocéliande — version éditée")
        self.page.locator("#panel .story-tile").first.click()
        self.assertIn("Narration humaine", self.page.locator("#panel").inner_text())
        self.review("storyboard")
        self.review("analysis")
        self.assertEqual(self.page.locator("#status").inner_text(), "Approuvé")
        self.page.locator('[data-tab="reviews"]').click()
        expect(self.page.locator("#panel .history-entry")).to_have_count(4)

    def test_analysis_guided_revision_invalidates_storyboard(self):
        self.sign_in()
        self.create("La cité d'Ys")
        self.page.locator('[data-tab="analysis"]').click()
        self.page.locator("#panel .review-buttons").get_by_role("button", name="Réviser").click()
        self.page.locator("#reviewComment").fill("Reformuler le message")
        self.page.locator("#edit-angle").fill("Mémoire des cités disparues")
        self.page.locator("#edit-message").fill("Une leçon tirée de la tradition orale")
        self.page.locator("#edit-checks").fill("Comparer les sources locales\nVérifier la datation")
        self.page.locator("#confirmReview").check()
        self.page.locator("#submitReview").click()
        self.page.locator("#reviewDialog").wait_for(state="hidden")
        self.assertIn("Mémoire des cités", self.page.locator("#panel").inner_text())
        self.page.locator('[data-tab="storyboard"]').click()
        self.assertIn("obsolète", self.page.locator("#panel").inner_text())
        expect(self.page.locator("#panel .review-buttons").get_by_role("button", name="Accepter")).to_have_count(0)
        expect(self.page.locator("#panel .review-buttons").get_by_role("button", name="Réviser")).to_be_visible()
        self.assertNotEqual(self.page.locator("#status").inner_text(), "Approuvé")

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
        expect(self.page.locator(".run-item")).to_have_count(23)
        self.page.locator("#filter").fill("numéro 22")
        expect(self.page.locator(".run-item")).to_have_count(1)
        self.page.locator("#filter").fill("")
        self.page.locator(".run-item").first.click()
        self.page.locator("#detail").wait_for(state="visible")
        self.page.locator("#home").click()
        self.page.locator("#library").wait_for(state="visible")
        self.page.go_back()
        self.page.locator("#detail").wait_for(state="visible")
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.assertLessEqual(
            self.page.evaluate("document.documentElement.scrollWidth"),
            self.page.evaluate("window.innerWidth") + 1)
        self.page.locator("#menu").click()
        self.assertIn("open", self.page.locator("#sidebar").get_attribute("class"))
        self.page.locator("#home").click()
        self.assertTrue(self.page.locator("#library").is_visible())

    def test_stories_tiles_scene_fields_and_character_drilldown(self):
        self.sign_in()
        self.create("Le phare de Bretagne")
        self.page.locator("#home").click()
        tile = self.page.locator("#storyCards .story-tile").first
        expect(tile).to_be_visible()
        tile.click()
        self.page.locator("#panel .story-tile").first.click()
        expect(self.page.locator("#panel .scene-element-grid .element-link")).to_have_count(8)
        self.page.get_by_role("button", name="Palette de couleurs").click()
        expect(self.page.locator("#panel")).to_contain_text("bleu")
        self.page.get_by_role("button", name="Retour à la scène").click()
        self.page.get_by_role("button", name="Un marin").click()
        expect(self.page.locator("#panel")).to_contain_text("Manteau de laine rouge")
        self.page.get_by_role("button", name="Retour à l'histoire").click()
        expect(self.page.locator("#panel .story-tile")).to_have_count(3)

    def test_atelier_composer_and_export_without_mutating_history(self):
        self.sign_in()
        self.create("Le phare de Bretagne")
        composer = self.page.locator("#storyComposer")
        expect(composer).to_be_visible()
        expect(composer.locator("[data-composer]")).to_have_count(10)
        composer.locator('[data-composer="colors"]').click()
        expect(self.page.locator("#panel")).to_contain_text("Couleurs")
        expect(self.page.locator("#panel")).to_contain_text("bleu")
        composer.locator('[data-composer="characters"]').click()
        expect(self.page.locator("#panel")).to_contain_text("Un marin")
        composer.locator('[data-composer="overview"]').click()
        expect(self.page.locator("#panel .story-tile")).to_have_count(3)
        with self.page.expect_download() as info:
            self.page.locator("#exportStory").click()
        exported = json.loads(Path(info.value.path()).read_text(encoding="utf-8"))
        self.assertEqual(exported["format"], "arvor-storyboard-v1")
        self.assertEqual(len(exported["storyboard"]["scenes"]), 3)
        self.page.locator("#detailBack").click()
        expect(self.page.locator("#library")).to_be_visible()
        self.assertTrue(composer.is_hidden())

    def test_next_studio_private_login_and_library(self):
        with httpx.Client(base_url=self.base, headers=AUTH) as client:
            run = client.post("/editorial/runs", headers={"Idempotency-Key": str(uuid4())}, json={"topic":"Le murmure de Brocéliande"})
            self.assertEqual(run.status_code, 200)
        self.page.goto(self.base + "/studio/next")
        expect(self.page.locator("#login-screen")).to_be_visible()
        self.page.locator("#login-password").fill(PASSWORD)
        self.page.locator("#login-submit").click()
        expect(self.page.locator("#studio-shell")).to_be_visible()
        self.page.locator("#side-create").click()
        expect(self.page.locator("#editor")).to_be_visible()
        self.page.locator("#editor-cancel").click()
        self.assertEqual(self.page.locator(".story-card").count(), 1,
            "UI: " + self.page.locator("#content").inner_text()[:500]
            + " / Auth: " + self.page.locator("#login-error").inner_text())
        self.page.locator(".story-card [data-open]").click()
        expect(self.page.locator(".outline")).to_be_visible()
        self.page.locator('[data-panel="scenes"]').click()
        expect(self.page.locator(".scene-row")).to_have_count(3)

    def test_next_studio_real_creation_and_revision(self):
        self.page.goto(self.base + "/studio/next")
        self.page.locator("#login-password").fill(PASSWORD)
        self.page.locator("#login-submit").click()
        expect(self.page.locator("#studio-shell")).to_be_visible()
        self.page.locator("#side-create").click()
        self.page.locator("#edit-topic").fill("La légende du vent")
        self.page.locator("#editor-form button[type=submit]").click()
        expect(self.page.locator(".story-banner h1")).to_have_text("La légende du vent")
        self.page.locator('[data-action="edit-story"]').first.click()
        self.page.locator("#edit-summary").fill("Une histoire de vent et de mémoire")
        with self.page.expect_response("**/studio/api/runs/*/steps/storyboard/review") as response_info:
            self.page.locator("#editor-form button[type=submit]").click()
        result = response_info.value
        self.assertEqual(result.status, 200, result.text()[:500])
        self.page.wait_for_timeout(300)
        self.assertIn("Une histoire de vent", self.page.locator(".story-banner").inner_text(),
                      "Révision: " + self.page.locator("#toast").inner_text())

    def test_accessible_tab_navigation_and_small_text_contrast(self):
        self.sign_in()
        self.page.locator("#heroCreate").click()
        self.assertTrue(self.page.get_by_role("dialog", name="Donnez vie à une légende.").is_visible())
        self.page.locator("#newDialog .close").first.click()
        self.create("La forêt enchantée")
        tab = self.page.locator('[data-tab="storyboard"]')
        tab.focus()
        self.page.keyboard.press("End")
        self.assertEqual(self.page.locator('[data-tab="reviews"]').get_attribute("aria-selected"), "true")
        self.assertEqual(self.page.locator("#panel").get_attribute("aria-labelledby"), "tab-reviews")
        self.page.keyboard.press("Home")
        self.assertEqual(tab.get_attribute("aria-selected"), "true")
        self.assertEqual(tab.get_attribute("tabindex"), "0")
        self.assertEqual(self.page.locator('[data-tab="reviews"]').get_attribute("tabindex"), "-1")
        color = self.page.locator(".metric span").first.evaluate(
            "(element) => getComputedStyle(element).color")
        from re import findall
        channel = [int(v) / 255 for v in findall(r"\d+", color)[:3]]
        self.assertEqual(len(channel), 3)
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                  for v in channel]
        luminance = sum(a * b for a, b in zip((0.2126, 0.7152, 0.0722), linear))
        self.assertGreaterEqual((1.05 / (luminance + 0.05)), 4.5)

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
        expect(self.page.locator("#reviewDialog")).to_be_visible()
        expect(self.page.locator("#reviewError")).to_contain_text("brouillon est conservé")
        self.page.locator("#reviewDialog .close").first.click()
        self.assertEqual(len(calls), 1)
        # Conflict is reported inside the preserved dialog rather than discarding it.
        self.page.unroute(pattern)
        self.review("storyboard")
        self.assertEqual(self.page.locator("#status").inner_text(), "À valider")

    def test_async_202_polling_reaches_human_validation_without_replay(self):
        self.sign_in()
        run_id = self.create("Asynchrone simulée")
        expect(self.page.locator("#status")).to_have_text("En attente")
        expect(self.page.locator("#status")).to_have_text("À valider", timeout=15000)
        self.assertTrue(self.page.locator("#decisionFoot").is_visible())
        self.assertTrue(self.page.locator("#reconcile").is_hidden())
        with httpx.Client(base_url=self.base) as client:
            self.assertEqual(client.get("/__fixture__/counts").json()["generate"], 1)
        self.assertEqual(self.page.evaluate("location.hash.slice(5)"), run_id)

    def test_terminal_failure_allows_fresh_idempotency_key(self):
        self.sign_in()
        self.page.locator("#heroCreate").click()
        self.page.locator("#topic").fill("Erreur IA simulée")
        self.page.locator("#submitNew").click()
        self.page.locator("#newDialog").wait_for(state="hidden")
        expect(self.page.locator("#notice")).to_contain_text("nouvelle clé")
        self.assertEqual(self.page.locator("#status").inner_text(), "Échec")
        first = self.page.evaluate("location.hash.slice(5)")
        self.page.locator("#sideCreate").click()
        self.assertEqual(self.page.locator("#topic").input_value(), "Erreur IA simulée")
        self.page.locator("#submitNew").click()
        self.page.locator("#newDialog").wait_for(state="hidden")
        expect(self.page.locator("#status")).to_have_text("Échec")
        second = self.page.evaluate("location.hash.slice(5)")
        self.assertNotEqual(first, second)
        with httpx.Client(base_url=self.base) as client:
            self.assertEqual(client.get("/__fixture__/counts").json()["generate"], 2)

    def test_stale_run_reconciliation_is_explicit_and_not_retried(self):
        self.sign_in()
        run_id = self.create("Légende interrompue")
        with httpx.Client(base_url=self.base) as client:
            self.assertEqual(client.post("/__fixture__/stale/" + run_id).status_code, 200)
        self.page.locator("#refresh").click()
        expect(self.page.locator("#status")).to_contain_text("En cours")
        expect(self.page.locator("#status")).to_contain_text("Résultat incertain")
        expect(self.page.locator("#reconcile")).to_be_visible()
        self.page.locator("#reconcile").click()
        expect(self.page.locator("#status")).to_have_text("Échec")
        expect(self.page.locator("#notice")).to_contain_text("interrompue")
        self.assertTrue(self.page.locator("#reconcile").is_hidden())
        with httpx.Client(base_url=self.base) as client:
            self.assertEqual(client.get("/__fixture__/counts").json()["generate"], 1)

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

    def next_sign_in(self):
        self.context.clear_cookies()
        self.page.goto(self.base + '/studio/next')
        self.page.locator('#login-password').fill(PASSWORD)
        self.page.locator('#login-submit').click()
        expect(self.page.locator('#studio-shell')).to_be_visible()

    def next_create(self):
        self.page.locator('#side-create').click()
        self.page.locator('#edit-topic').fill('Recette privée synthétique')
        self.page.locator('#editor-form button[type=submit]').click()
        expect(self.page.locator('.story-banner')).to_be_visible()

    def test_audit_next_human_approval_and_approved_actions(self):
        self.next_sign_in()
        self.next_create()
        self.page.locator('[data-accept="analysis"]').click()
        expect(self.page.locator('#toast')).to_contain_text('relecture humaine')
        self.page.locator('#review-next-analysis').check()
        self.page.locator('[data-accept="analysis"]').click()
        expect(self.page.locator('#review-next-analysis')).to_have_count(0)
        self.page.locator('#review-next-storyboard').check()
        self.page.locator('[data-accept="storyboard"]').click()
        expect(self.page.locator('[data-accept]')).to_have_count(0)
        expect(self.page.locator('.story-banner')).to_contain_text('Validée')
        self.page.locator('[data-action="edit-story"]').first.click()
        expect(self.page.locator('#editor')).to_be_visible()

    def test_audit_classic_conflict_preserves_revision_draft(self):
        self.sign_in()
        self.create('Brouillon concurrent')
        self.page.locator('#panel .review-buttons').get_by_role('button', name='Réviser').click()
        self.page.locator('#edit-synopsis').fill('Mon brouillon local à conserver')
        self.page.locator('#reviewComment').fill('Révision synthétique de test')
        calls=[]
        def conflict(route):
            calls.append(1)
            route.fulfill(status=409, content_type='application/json', body='{"detail":"conflict"}')
        self.page.route('**/studio/api/runs/*/steps/*/review', conflict)
        self.page.locator('#confirmReview').check()
        self.page.locator('#submitReview').click()
        expect(self.page.locator('#reviewDialog')).to_be_visible()
        expect(self.page.locator('#edit-synopsis')).to_have_value('Mon brouillon local à conserver')
        expect(self.page.locator('#submitReview')).to_be_disabled()
        expect(self.page.locator('#reviewError')).to_contain_text('Version courante')
        self.assertEqual(len(calls),1)

    def test_audit_next_conflict_preserves_editor_draft(self):
        self.next_sign_in()
        self.next_create()
        self.page.locator('[data-action="edit-story"]').first.click()
        self.page.locator('#edit-summary').fill('Brouillon next à conserver')
        calls=[]
        def conflict(route):
            calls.append(1)
            route.fulfill(status=409, content_type='application/json', body='{"detail":"conflict"}')
        self.page.route('**/studio/api/runs/*/steps/*/review', conflict)
        self.page.locator('#editor-form button[type=submit]').click()
        expect(self.page.locator('#edit-summary')).to_have_value('Brouillon next à conserver')
        expect(self.page.locator('.edit-conflict')).to_contain_text('Version courante')
        expect(self.page.locator('#editor-form button[type=submit]')).to_be_disabled()
        self.assertEqual(len(calls),1)

    def test_audit_xss_dynamic_story_scene_character_and_history(self):
        self.sign_in()
        self.create('XSS synthétique')
        payload='"><img src=x onerror="window.__xss=1"><svg onload="window.__xss=2">'
        def hostile(route):
            response=route.fetch()
            data=response.json()
            def inject(value):
                if isinstance(value,dict):
                    for key,item in list(value.items()):
                        if key in {'title','synopsis','topic','narration','landscape','appearance','name','angle','message','prompt','image_prompt','shot','emotion','sound','role','personality'} and isinstance(item,str):value[key]=payload
                        else:inject(item)
                elif isinstance(value,list):
                    for item in value:inject(item)
            inject(data)
            route.fulfill(response=response,json=data)
        self.page.route('**/studio/api/runs**', hostile)
        self.page.locator('#refresh').click()
        expect(self.page.locator('#storyTitle')).to_have_text(payload)
        self.page.locator('[data-tab="analysis"]').click()
        self.assertEqual(self.page.locator('#panel img[src="x"], #panel svg[onload]').count(),0)
        self.assertIsNone(self.page.evaluate('window.__xss'))
        self.next_sign_in()
        self.page.locator('.story-card [data-open]').first.click()
        expect(self.page.locator('.story-banner h1')).to_have_text(payload)
        for panel in ('overview','scenario','scenes','characters','landscapes','colors','shots','emotions','sounds','history','media'):
            self.page.locator('[data-panel="'+panel+'"]').click()
            self.assertEqual(self.page.locator('#content img[src="x"], #content svg[onload]').count(),0)
        self.assertIsNone(self.page.evaluate('window.__xss'))

    def test_audit_xss_journal_and_all_admin_tabs(self):
        payload='<img src=x onerror="window.__xss=3">'
        overview={'repository_url':'https://github.com/richardyoann/saas-directeur-editorial',
          'epics':[{'number':1,'title':payload,'state':'open'}],
          'issues':[{'number':1,'title':payload,'state':'open'}],
          'pull_requests':[{'number':2,'title':payload,'state':'open','draft':True,
                            'created_at':'2026-10-21T00:00:00Z'}], 'deliveries':[], 'source_truncated':{}}
        commits={'commits':[{'sha':'a'*40,'message':payload,'when':'2026-10-21T00:00:00Z'}],'partial':False}
        def metadata(route):
            data=commits if '/commits' in route.request.url else {'runs':[]} if '/ci' in route.request.url else overview
            route.fulfill(status=200,json=data)
        self.page.route('**/studio/api/conception**',metadata)
        self.sign_in()
        self.create(payload)
        self.page.locator('#journalNav').click()
        expect(self.page.locator('#journal')).to_contain_text(payload)
        self.page.locator('#conceptionNav').click()
        expect(self.page.locator('#arvorAdminSurface')).to_contain_text(payload)
        for title in ('Epics & stories','Pull requests','Commits','Agenda'):
            self.page.locator('#arvorAdminTabs').get_by_role('tab',name=title).click()
            self.assertEqual(self.page.locator('#arvorAdminSurface img[src="x"]').count(),0)
        self.next_sign_in()
        self.page.locator('#sidebar [data-route="admin"]').click()
        expect(self.page.locator('#admin-stage')).to_contain_text(payload)
        for title in ('Epics & stories','Pull requests','Commits','Agenda'):
            self.page.locator('.admin-tabs').get_by_role('tab',name=title).click()
            self.assertEqual(self.page.locator('#content img[src="x"]').count(),0)
        self.assertIsNone(self.page.evaluate('window.__xss'))

    def test_audit_next_interruption_is_visible_and_reconciled_only_on_click(self):
        self.next_sign_in()
        self.next_create()
        with httpx.Client(base_url=self.base,headers=AUTH) as client:
            run_id=client.get('/editorial/runs').json()['runs'][0]['id']
            self.assertEqual(client.post('/__fixture__/stale/'+run_id).status_code,200)
        self.page.reload()
        expect(self.page.locator('.story-card [data-open]')).to_be_visible()
        self.page.locator('.story-card [data-open]').click()
        expect(self.page.locator('[data-reconcile]')).to_be_visible()
        expect(self.page.locator('#workbench')).to_contain_text('Résultat IA incertain')
        with httpx.Client(base_url=self.base) as client:
            self.assertEqual(client.get('/__fixture__/counts').json()['generate'],1)
        self.page.locator('[data-reconcile]').click()
        expect(self.page.locator('.story-banner')).to_contain_text('Échec')
        with httpx.Client(base_url=self.base) as client:
            self.assertEqual(client.get('/__fixture__/counts').json()['generate'],1)


if __name__ == "__main__":
    unittest.main()
