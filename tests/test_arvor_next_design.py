"""Static non-regression guards for the Arvor design preview (no backend required)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_next_preview_preserves_session_and_scoped_assets():
    html = (ROOT / "apps/web/arvor_next.html").read_text(encoding="utf-8")
    js = (ROOT / "apps/web/arvor_next.js").read_text(encoding="utf-8")
    assert "/studio/assets/arvor_next.css" in html
    assert 'id="nav-count">0<' in html
    assert "/studio/session" in js
    assert "credentials:'same-origin'" in js
    assert "X-CSRF-Token" in js


def test_next_preview_has_no_invented_journal_timeline():
    js = (ROOT / "apps/web/arvor_next.js").read_text(encoding="utf-8")
    assert "events=stories.filter(x=>x.created)" in js
    assert "Création enregistrée" in js
    assert "Ouvrir l’historique" in js
    assert "data-history" in js
    assert "Traces de création" not in js


def test_next_preview_has_accessible_navigation_and_empty_result():
    css = (ROOT / "apps/web/arvor_next.css").read_text(encoding="utf-8")
    js = (ROOT / "apps/web/arvor_next.js").read_text(encoding="utf-8")
    assert 'aria-current' in js
    assert 'empty-results' in css and 'empty-results' in js
    assert '@media(prefers-reduced-motion:reduce)' in css
    assert '#0E2B23' in css
