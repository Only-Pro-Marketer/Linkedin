"""Phase 3: Home, Brand Voice, navigation and page wiring."""

import pathlib
import shutil

import pytest

from tests.conftest import make_post

TEMPLATE = pathlib.Path(__file__).parent / "fixtures" / "soul_template.md"


@pytest.fixture
def temp_soul(tmp_path, monkeypatch):
    """Work on a copy of the blank template so tests never touch the real brand file."""
    from content import brand
    soul = tmp_path / "soul.md"
    shutil.copy(TEMPLATE, soul)
    monkeypatch.setattr(brand, "SOUL_PATH", soul)
    monkeypatch.setattr(brand, "_cache", {"mtime": None, "text": ""})
    return soul


def test_home_shows_checklist_and_review(client, db, temp_soul):
    make_post(db, quality_score=88, quality_report='{"score": 88, "status": "ready", "blockers": []}')
    html = client.get("/").text
    assert "Finish setting up" in html
    assert "Describe your brand voice" in html
    assert "Ready for your review" in html and "Line one of a test post." in html


def test_queue_moved_to_queue_path(client):
    assert client.get("/queue").status_code == 200
    assert 'href="/queue"' in client.get("/").text


def test_brand_page_lists_guided_sections(client, temp_soul):
    html = client.get("/brand").text
    for title in ("Who I Am", "Voice Fingerprint", "Content Pillars (What I Post About)"):
        assert title in html


def test_brand_save_round_trip(client, temp_soul):
    from content.brand import author_identity, brand_status, get_niche
    before = brand_status()["percent"]
    sections = {
        "Who I Am": "**Name:** Jane Doe\n**Role:** Founder\n**Company:** Acme Growth (acme.com)\n\nI run a 9-person agency.",
        "What My Business Does": "We are an e-commerce growth agency for DTC brands.\n\n**Core services:**\n- Email",
        "Who I Talk To (Target Audience)": "- DTC founders doing $1M–$20M",
        "My LinkedIn Voice & Tone": "Plain, direct, specific. Numbers over adjectives.",
        "Content Pillars (What I Post About)": "1. **Retention** — flows and LTV\n2. **Agency life** — pricing and hiring",
        "Voice Fingerprint": "- Short sentences\n- Open with a date",
    }
    r = client.post("/api/brand", json={"sections": sections})
    assert r.status_code == 200
    status = r.json()["status"]
    assert status["filled"] is True and status["percent"] == 100 > before
    assert author_identity() == {"name": "Jane Doe", "role": "Founder", "company": "Acme Growth"}
    assert get_niche().startswith("We are an e-commerce growth agency")
    text = temp_soul.read_text()
    assert "## Voice Fingerprint" in text and "## How to Use This File" in text  # new + preserved sections
    assert text.index("## Voice Fingerprint") < text.index("## How to Use This File")
    assert (temp_soul.parent / "soul.md.bak").exists()


def test_brand_rejects_unknown_sections(client, temp_soul):
    assert client.post("/api/brand", json={"sections": {"Evil": "x"}}).status_code == 400


def test_generate_reports_errors(client, fake_llm):
    fake_llm["text"]["generate"] = ""
    import content.generator as gen_mod

    def fail(self, prompt, feature="generate"):
        self.last_error = "Claude is rate limiting requests. Wait a minute and try again."
        return None

    orig = gen_mod.ContentGenerator._call_claude
    gen_mod.ContentGenerator._call_claude = fail
    try:
        r = client.post("/api/generate", json={"count": 1})
    finally:
        gen_mod.ContentGenerator._call_claude = orig
    assert r.status_code == 502 and "rate limiting" in r.json()["error"]


def test_static_assets_served(client):
    for path in ("/static/js/app.js", "/static/js/post-editor.js", "/static/css/components.css"):
        assert client.get(path).status_code == 200, path
