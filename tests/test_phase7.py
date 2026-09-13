"""Phase 7: Profile Optimizer, Settings, manual stats and AI usage."""

from datetime import datetime

import httpx

from config import settings
from database.models import LLMUsage, PostPerformance, PostStatus
from tests.conftest import connect_linkedin, make_post

PARTS = ["headline", "about", "experience", "skills", "featured", "custom_url", "recommendations", "banner", "photo"]


def test_profile_optimizer_scores_all_parts(client, fake_llm):
    fake_llm["json"]["profile_review"] = {
        "parts": [{"part": p, "score": 12 if p == "about" else 6, "verdict": f"{p} verdict", "fix": f"fix {p}"}
                  for p in PARTS if p != "banner"],
        "headline_options": ["Founder, Acme Growth | Retention for DTC brands doing $1M–$20M", "x" * 300],
        "about_rewrite": "I help DTC brands keep the customers they already paid for.",
        "experience_bullets": ["Grew retention revenue for [client type] by [your number]"],
        "top_priority": "Rewrite the headline around who you help.",
    }
    r = client.post("/api/profile-optimizer", json={
        "headline": "CEO", "about": "We do marketing.", "profile_url": "https://www.linkedin.com/in/jane-doe-4b1a9c2e1"})
    assert r.status_code == 200, r.text
    body = r.json()
    parts = {p["part"]: p for p in body["parts"]}
    assert list(parts) == PARTS
    assert parts["about"]["score"] == 10  # clamped to 0-10
    assert parts["banner"]["score"] is None  # not returned by the model
    assert parts["custom_url"]["score"] == 4 and "random" in parts["custom_url"]["verdict"]
    assert body["headline_options"] == ["Founder, Acme Growth | Retention for DTC brands doing $1M–$20M"]
    assert 0 < body["overall"] <= 100
    assert "Score my profile" in client.get("/profile-optimizer").text


def test_profile_optimizer_needs_headline_or_about(client, fake_llm):
    assert client.post("/api/profile-optimizer", json={"skills": "CRO"}).status_code == 400


def test_settings_save_and_validate(client):
    r = client.post("/api/settings", json={"values": {"POSTS_PER_DAY": 2, "AUTO_REPAIR": False}})
    assert r.status_code == 200, r.text
    assert settings.POSTS_PER_DAY == 2 and settings.AUTO_REPAIR is False
    assert client.post("/api/settings", json={"values": {"POSTS_PER_DAY": 99}}).status_code == 400
    assert client.post("/api/settings", json={"values": {"ANTHROPIC_API_KEY": "x"}}).status_code == 400
    assert client.post("/api/settings", json={"values": {"AUTO_REPAIR": 1}}).status_code == 400


def test_settings_page_sections(client):
    html = client.get("/settings").text
    for text in ("Automation and limits", "Posting times", "AI usage", "Background jobs", "Read post stats automatically"):
        assert text in html


def test_linkedin_connection_test(client, db, monkeypatch):
    import dashboard.routers.settings as mod
    from linkedin.api_client import LinkedInAPIClient

    assert client.post("/api/linkedin/test").json()["ok"] is False
    connect_linkedin(db)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"name": "Jane Doe", "sub": "abc123"}))
    monkeypatch.setattr(mod, "LinkedInAPIClient", lambda token: LinkedInAPIClient(token, transport=transport))
    r = client.post("/api/linkedin/test").json()
    assert r["ok"] is True and "Jane Doe" in r["message"]


def test_manual_stats_feed_history(client, db):
    post = make_post(db, status=PostStatus.POSTED, posted_at=datetime.utcnow())
    r = client.post(f"/api/history/{post.id}/stats", json={"impressions": 1200, "likes": 40, "comments": 9, "shares": 2})
    assert r.status_code == 200, r.text
    perf = db.query(PostPerformance).filter_by(post_id=post.id).one()
    assert (perf.impressions, perf.likes, perf.comments, perf.shares) == (1200, 40, 9, 2)
    row = client.get("/api/history").json()[0]
    assert row["impressions"] == 1200 and row["likes"] == 40
    queued = make_post(db)
    assert client.post(f"/api/history/{queued.id}/stats", json={"likes": 1}).status_code == 400
    assert client.post(f"/api/history/{post.id}/stats", json={"likes": -1}).status_code == 422


def test_usage_by_feature(db):
    import llm
    db.add_all([
        LLMUsage(feature="t7_write", model=settings.CLAUDE_MODEL, input_tokens=1000, output_tokens=500),
        LLMUsage(feature="t7_write", model=settings.CLAUDE_MODEL, ok=False, error="boom"),
        LLMUsage(feature="t7_comment", model=settings.CLAUDE_MODEL, input_tokens=200, output_tokens=100),
    ])
    db.commit()
    rows = {r["feature"]: r for r in llm.usage_by_feature(30)}
    assert rows["t7_write"]["calls"] == 2 and rows["t7_write"]["errors"] == 1
    assert rows["t7_comment"]["calls"] == 1 and rows["t7_comment"]["errors"] == 0


def test_calendar_slot_validation(client):
    assert client.post("/api/calendar", json={"day_of_week": 1, "time_slot": "25:99", "is_active": True}).status_code == 400
    r = client.post("/api/calendar", json={"day_of_week": 6, "time_slot": "07:15", "is_active": True})
    assert r.status_code == 200, r.text
    assert any(s["time_slot"] == "07:15" for s in client.get("/api/calendar").json()["slots"])
    client.delete(f"/api/calendar/{r.json()['id']}")
