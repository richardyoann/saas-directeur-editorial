"""Non-regression checks for private Arvor V2. Executed by unittest CI."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ArvorNextDesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "apps/web/arvor_next.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "apps/web/arvor_next.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "apps/web/arvor_next.css").read_text(encoding="utf-8")

    def test_preview_keeps_authenticated_session_and_csrf(self):
        self.assertIn("/studio/assets/arvor_next.css", self.html)
        self.assertIn('id="nav-count">0<', self.html)
        self.assertIn("/studio/session", self.js)
        self.assertIn("credentials:'same-origin'", self.js)
        self.assertIn("X-CSRF-Token", self.js)
        self.assertIn('id="login-form"', self.html)

    def test_journal_does_not_invent_prompt_or_revision_events(self):
        self.assertIn("events=stories.filter(x=>x.created)", self.js)
        self.assertIn("Création enregistrée", self.js)
        self.assertIn("Ouvrir l’historique", self.js)
        self.assertIn("data-history", self.js)
        self.assertIn("'/history'", self.js)
        self.assertNotIn("Traces de création", self.js)

    def test_navigation_and_empty_search_are_accessible(self):
        self.assertIn("aria-current", self.js)
        self.assertIn("empty-results", self.css)
        self.assertIn("empty-results", self.js)
        self.assertIn("@media(prefers-reduced-motion:reduce)", self.css)
        self.assertIn("#0E2B23", self.css)

    def test_main_studio_remains_explicit_separate_route(self):
        api = (ROOT / "apps/api/studio.py").read_text(encoding="utf-8")
        self.assertIn('ASSETS / "studio.html"', api)
        self.assertIn('ASSETS / "arvor_next.html"', api)
        self.assertIn('@router.get("/next")', api)


if __name__ == "__main__":
    unittest.main()
