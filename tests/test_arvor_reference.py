"""Contracts for the additional private Arvor UI surfaces."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reference_assets_are_wired():
    html = (ROOT / "apps/web/studio.html").read_text()
    api = (ROOT / "apps/api/studio.py").read_text()
    for asset in ("arvor_reference.js", "arvor_reference.css"):
        assert (ROOT / "apps/web" / asset).is_file()
        assert f"/studio/assets/{asset}" in html
        assert f'"{asset}"' in api


def test_reference_navigation_has_restricted_data_sources():
    js = (ROOT / "apps/web/arvor_reference.js").read_text()
    assert "/studio/api/runs?limit=50" in js
    assert "/studio/api/conception" in js
    assert "LOCAL_PC_APPROVED_SHA" not in js
    assert "Authorization" not in js


def test_existing_login_and_studio_still_exist():
    html = (ROOT / "apps/web/studio.html").read_text()
    for required in ('id="loginForm"', 'id="conceptionNav"', 'id="storyCards"'):
        assert required in html
