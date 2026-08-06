"""V1-9 release gates: store package, demo materials, CI, version consistency."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_version_file_matches_extension_manifest() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == version
    assert manifest["manifest_version"] == 3
    assert manifest["name"] == "AI Memory Agent"


def test_extension_icons_present() -> None:
    for name in ("icon-16.png", "icon-48.png", "icon-128.png"):
        path = ROOT / "extension" / "icons" / name
        assert path.is_file(), path
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_store_listing_package_ready() -> None:
    listing = ROOT / "docs" / "store" / "CHROME_WEB_STORE_LISTING.md"
    text = listing.read_text(encoding="utf-8")
    assert "Ready to submit" in text
    assert "Not submitted" in text or "not submitted" in text.lower()
    assert "/privacy" in text
    # short description ≤ 132 chars (extract the table cell)
    m = re.search(
        r"\*\*Short description\*\*[^\n]*\|\s*([^\n|]+)\|",
        text,
    )
    assert m, "short description row missing"
    short = m.group(1).strip()
    assert len(short) <= 132, f"short description is {len(short)} chars: {short!r}"
    checklist = (ROOT / "docs" / "store" / "SUBMISSION_CHECKLIST.md").read_text(encoding="utf-8")
    assert "placeholder" in checklist.lower()
    assert (ROOT / "docs" / "store" / "LINKEDIN_LAUNCH.md").is_file()


def test_store_promo_assets_exist() -> None:
    assets = ROOT / "docs" / "store" / "assets"
    promo = assets / "promo-small-440x280.png"
    marquee = assets / "marquee-1400x560.png"
    assert promo.is_file()
    assert marquee.is_file()
    assert promo.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # placeholders must be labeled as such
    placeholders = list(assets.glob("screenshot-*-placeholder.png"))
    assert len(placeholders) >= 1
    readme = (assets / "README.md").read_text(encoding="utf-8")
    assert "PLACEHOLDER" in readme.upper() or "placeholder" in readme.lower()


def test_security_md_and_license() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "Supported versions" in security or "supported" in security.lower()
    assert "vulnerability" in security.lower()
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT" in license_text


def test_ci_workflow_yaml_valid() -> None:
    path = ROOT / ".github" / "workflows" / "ci.yml"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    # Structural checks without requiring PyYAML in requirements.txt
    assert re.search(r"(?m)^name:\s*CI\s*$", text)
    assert "pytest -q" in text
    assert "VERSION" in text
    assert "actions/checkout@" in text
    assert "actions/setup-python@" in text
    assert "python-version:" in text
    assert "3.11" in text
    assert re.search(r"(?m)^jobs:\s*$", text)
    assert re.search(r"(?m)^\s+pytest:\s*$", text)
    assert "timeout-minutes:" in text
    # No tabs (common YAML footgun)
    assert "\t" not in text


def test_demo_script_and_seed_script() -> None:
    demo = (ROOT / "docs" / "V1_DEMO_SCRIPT.md").read_text(encoding="utf-8")
    assert "seed_demo.py" in demo
    assert "Load unpacked" in demo or "load unpacked" in demo.lower()
    seed = ROOT / "scripts" / "seed_demo.py"
    assert seed.is_file()
    gen = ROOT / "scripts" / "generate_store_assets.py"
    assert gen.is_file()


def test_readme_reflects_v1_ship() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "AI Memory Agent" in readme
    assert "1.9.0" in readme
    assert "Chrome" in readme
    # stale scaffold claims should be gone
    assert "Streamlit (Phase 5+)" not in readme
    assert "Phase 2 Endpoints" not in readme


def test_v1_9_doc_marks_complete() -> None:
    doc = (ROOT / "docs" / "V1_9_DEMO_STORE_LAUNCH.md").read_text(encoding="utf-8")
    assert "Complete" in doc
    assert "Version 2" in doc or "Out of scope" in doc


def test_privacy_url_still_served(tmp_path) -> None:
    """V1-8 privacy page remains the CWS privacy URL target."""
    from unittest.mock import patch

    from app.config import Settings, get_settings
    from app.db.schema import SCHEMA_VERSION, migrate
    from app.main import app
    from app.api.dependencies import get_app_settings
    from app.services.health_service import HealthService
    from app.db.repositories.memory_repository import MemoryRepository
    from app.api.dependencies import get_health_service

    chroma_dir = tmp_path / "chroma"
    settings = Settings(
        app_name="AI Memory Search Agent (test)",
        chroma_persist_dir=str(chroma_dir),
        chroma_collection_name="test_memory_items",
        sqlite_path=str(tmp_path / "v19.db"),
        debug=True,
        hierarchical_retrieval_enabled=False,
        semantic_cache_enabled=False,
        jobs_enabled=False,
        pwa_enabled=True,
        auth_enabled=False,
        local_demo_mode=True,
        rate_limit_enabled=False,
        schema_version=SCHEMA_VERSION,
    )
    migrate(settings)
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_app_settings] = lambda: settings
    app.dependency_overrides[get_health_service] = lambda: HealthService(
        settings=settings,
        repository=MemoryRepository(settings),
    )
    with patch("app.main.get_settings", lambda: settings):
        with TestClient(app) as client:
            resp = client.get("/privacy")
            assert resp.status_code == 200
            assert "privacy" in resp.text.lower()
            disc = client.get("/static/privacy-disclosure.txt")
            assert disc.status_code == 200
            assert "Single purpose" in disc.text or "single purpose" in disc.text.lower()


def test_seed_demo_script_runs(tmp_path) -> None:
    db = tmp_path / "seed.db"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_demo.py"), "--sqlite", str(db)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Seeded" in result.stdout
    assert db.is_file()


def test_generate_store_assets_script_idempotent(tmp_path, monkeypatch) -> None:
    """Smoke: generator module entrypoint produces PNGs (writes under docs/store/assets)."""
    # Import and call helpers only — avoid overwriting repo assets mid-suite if broken.
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_store_assets as gen  # type: ignore

    out = tmp_path / "out.png"
    # 2x2 red
    rgba = bytes([255, 0, 0, 255] * 4)
    gen.write_rgba_png(out, 2, 2, rgba)
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    w, h, data = gen.read_png_rgba(ROOT / "extension" / "icons" / "icon-16.png")
    assert w == 16 and h == 16
    assert len(data) == 16 * 16 * 4

