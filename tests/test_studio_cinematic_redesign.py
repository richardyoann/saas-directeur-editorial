"""Arvor Studio cinematic redesign — Lot 1 static contracts (2026-11-01).

These tests cover the design system tokens, the cinematic shell navigation and
the dashboard implementation surfaces of apps/web/arvor_next.* without starting
the FastAPI app. Backend contracts remain covered by tests.test_studio_*.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CinematicDesignSystemTests(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / "apps/web/arvor_next.css").read_text(encoding="utf-8")

    def test_cinematic_palette_tokens_are_centralized(self):
        expected = {
            "--bg": "#0B1115",
            "--panel": "#121B20",
            "--panel-2": "#18242A",
            "--line": "#29373C",
            "--text": "#ECF0EC",
            "--muted": "#91A19F",
            "--gold": "#D2B175",
            "--teal": "#6AC4B5",
            "--red": "#EB917C",
        }
        for token, value in expected.items():
            self.assertIn(f"{token}:{value}", self.css)

    def test_typography_uses_local_fonts_only(self):
        self.assertIn("--serif", self.css)
        self.assertIn("--sans", self.css)
        self.assertIn("--mono", self.css)
        self.assertNotIn("fonts.googleapis", self.css)
        self.assertNotIn("fonts.gstatic", self.css)

    def test_dark_background_and_panels_are_tokenized(self):
        self.assertIn("background:var(--bg)", self.css)
        self.assertIn("background:var(--panel)", self.css)
        self.assertIn("border:1px solid var(--line)", self.css)


class CinematicShellNavigationTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "apps/web/arvor_next.html").read_text(encoding="utf-8")
        self.js = (ROOT / "apps/web/arvor_next.js").read_text(encoding="utf-8")

    def test_six_screens_are_declared_in_shell(self):
        for route in ("overview", "stories", "conception", "production", "journal", "admin"):
            with self.subTest(route=route):
                self.assertIn(f'data-route="{route}"', self.html)

    def test_shell_keeps_private_session_and_content_targets(self):
        for id_ in ("login-screen", "login-form", "login-password", "login-error", "login-submit",
                    "studio-shell", "sidebar", "breadcrumb", "content", "nav-count", "side-create",
                    "mobile-toggle", "shade", "toast"):
            self.assertIn(f'id="{id_}"', self.html)

    def test_dashboard_and_new_views_are_implemented(self):
        for token in ("renderDashboard", "renderConception", "renderProduction", "renderPipeline",
                      "metric-grid", "action-card", "stage-stepper", "action-list"):
            self.assertIn(token, self.js)
        self.assertIn("route==='overview'", self.js)

    def test_navigation_covers_existing_real_endpoints(self):
        for token in ("/studio/api/runs", "/studio/api/conception", "/studio/api/conception/commits",
                      "/studio/api/conception/ci", "/studio/logout"):
            self.assertIn(token, self.js)


class CinematicResponsiveTests(unittest.TestCase):
    def setUp(self):
        self.css = (ROOT / "apps/web/arvor_next.css").read_text(encoding="utf-8")
        self.html = (ROOT / "apps/web/arvor_next.html").read_text(encoding="utf-8")

    def test_mobile_drawer_and_reduced_motion_are_defined(self):
        self.assertIn("prefers-reduced-motion", self.css)
        self.assertIn("translateX", self.css)
        self.assertIn('id="mobile-toggle"', self.html)
        self.assertIn('class="mobile-shade"', self.html)


if __name__ == "__main__":
    unittest.main()
