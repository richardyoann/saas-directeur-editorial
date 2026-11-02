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

    def test_story_duration_is_derived_from_real_scenes(self):
        self.assertIn("const storyDuration=", self.js)
        self.assertIn("const storyDurationText=", self.js)
        self.assertIn("Durée totale", self.js)
        self.assertIn("storyDurationText(s)", self.js)

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


class CinematicProductionCorrectiveTests(unittest.TestCase):
    """Lot 3 corrective contracts (2026-11-01): video export, navigation state,
    error states and quality control surfaced in apps/web/arvor_next.js."""

    def setUp(self):
        self.js = (ROOT / "apps/web/arvor_next.js").read_text(encoding="utf-8")

    def test_video_export_targets_private_media_content_route(self):
        self.assertIn("async function exportVideo", self.js)
        self.assertIn("/media/'+encodeURIComponent(video.id)+'/content", self.js)
        self.assertIn("if(!plan.approved||video?.status!=='ready'||!video?.id)return", self.js)
        self.assertIn("if(plan.run_id&&plan.run_id!==state.storyId)return", self.js)
        self.assertIn('$$(\'[data-action="export-video"]\')', self.js)
        self.assertNotIn("data-action=\"export\" && canExport", self.js)

    def test_story_switch_resets_production_state(self):
        self.assertIn("if(storyId&&storyId!==state.storyId){prodData=null;mediaData=null;historyData=null;journalData=null;journalError=null;journalPage=1;}", self.js)

    def test_production_error_state_is_rendered(self):
        self.assertIn("if(prodError)", self.js)
        self.assertIn("if(!plan){", self.js)
        self.assertIn("Consultation de la production", self.js)
        self.assertIn("prodError=e.message", self.js)

    def test_quality_control_separates_presence_technical_and_human_validation(self):
        self.assertIn("['Présence des médias'", self.js)
        self.assertIn("Validation technique", self.js)
        self.assertIn("Validation artistique (humaine)", self.js)
        self.assertIn("approved&&plan.duration_seconds===75", self.js)
        self.assertIn("missing.length===0", self.js)

    def test_export_button_uses_video_download_not_storyboard_json(self):
        self.assertIn('data-action="export-video"', self.js)
        self.assertIn("async function exportVideo", self.js)
        self.assertNotIn("data-action=\"export\" ${canExport", self.js)


class CinematicLot4JournalAdminTests(unittest.TestCase):
    """Lot 4 static contracts (2026-11-02): journal built on real traces and
    administration source states surfaced in apps/web/arvor_next.js."""

    def setUp(self):
        self.js = (ROOT / "apps/web/arvor_next.js").read_text(encoding="utf-8")

    def test_journal_uses_real_traces_not_fabricated_events(self):
        self.assertIn("/studio/api/runs/'+encodeURIComponent(id)+'/history", self.js)
        self.assertIn("/reviews?limit=50", self.js)
        self.assertNotIn("const rows=events.filter", self.js)

    def test_journal_displays_trace_metadata_and_pagination(self):
        for token in ("journalVisible", "journalData", "journalError", "journalPage",
                      "data-journal-page", "data-journal-retry", "TRACES RÉELLES",
                      "Traitement IA", "Décision humaine", "Version", "Agent"):
            self.assertIn(token, self.js)

    def test_admin_distinguishes_source_states(self):
        self.assertIn("adminError", self.js)
        self.assertIn("not_configured", self.js)
        self.assertIn("unavailable", self.js)
        self.assertIn("includes('configur')", self.js)


if __name__ == "__main__":
    unittest.main()
