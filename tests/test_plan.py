"""Phase 6: Plan (weekly plan with enforced guardrails) and Learn my voice."""

import pathlib
import shutil

import pytest

import llm
from database.models import ContentPlanItem, PostStatus, QueuedPost
from tests.conftest import DEFAULT_FAKE_POST, make_post


@pytest.fixture
def soul(tmp_path, monkeypatch):
    """A filled-in brand file in a temp dir, so tests never touch the real one."""
    from content import brand
    path = tmp_path / "soul.md"
    shutil.copy(pathlib.Path(__file__).parent / "fixtures" / "soul_template.md", path)
    monkeypatch.setattr(brand, "SOUL_PATH", path)
    monkeypatch.setattr(brand, "_cache", {"mtime": None, "text": ""})
    brand.save_sections({"Content Pillars (What I Post About)":
                         "1. **Retention** — flows, offers, LTV\n2. **Agency life** — pricing and hiring\n"
                         "3. **[Pillar 3]** — [brief description]"})
    return path


def _post(pillar, formula, goal="comments", topic="A topic"):
    return {"pillar": pillar, "goal": goal, "formula_id": formula, "topic": topic, "angle": "Lead with [your number]"}


def test_get_pillars_skips_placeholders(soul):
    from content.brand import get_pillars
    assert get_pillars() == ["Retention — flows, offers, LTV", "Agency life — pricing and hiring"]


def test_plan_week_enforces_guardrails(client, db, soul, fake_llm):
    make_post(db, formula_id="F4")  # used in the last 7 days
    fake_llm["json"]["plan_week"] = {"posts": [
        _post("Retention — flows, offers, LTV", "F4", topic="Why welcome flows fail"),
        _post("Retention — flows, offers, LTV", "F9", "saves", topic="A win-back checklist"),
        _post("Retention — flows, offers, LTV", "F9", "reposts", topic="Email is not dead"),
        _post("Agency life — pricing and hiring", "F99", "likes", topic="Our first hire"),
    ]}
    r = client.post("/api/plan/week", json={"count": 4, "focus": "Retention audit launch"})
    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    formulas = [i["formula_id"] for i in plan["items"]]
    assert len(set(formulas)) == 4 and "F4" not in formulas and "F99" not in formulas
    assert fake_llm["calls"].count("plan_week") == 2  # one retry with the violations
    assert any("60%" in w for w in plan["warnings"]) and any("repeat" in w for w in plan["warnings"])
    slots = [i["slot_at"] for i in plan["items"]]
    assert all(slots) and slots == sorted(slots)
    assert plan["focus"] == "Retention audit launch"


def test_draft_item_queues_for_review_with_angle_as_direction(client, db, soul, fake_llm, monkeypatch):
    fake_llm["json"]["plan_week"] = {"posts": [
        _post("Retention — flows, offers, LTV", "F10", topic="Welcome flows"),
        _post("Agency life — pricing and hiring", "F4", "likes", topic="First hire"),
        _post("Retention — flows, offers, LTV", "F7", "saves", topic="Win-back checklist"),
    ]}
    plan = client.post("/api/plan/week", json={"count": 3}).json()["plan"]
    item_id = plan["items"][0]["id"]

    seen = {}
    real_complete = llm.complete

    def complete(feature, user, **kw):
        if feature == "studio_write":
            seen["user"] = user
        return real_complete(feature, user, **kw)

    monkeypatch.setattr(llm, "complete", complete)
    r = client.post(f"/api/plan/items/{item_id}/draft")
    assert r.status_code == 200, r.text
    post = db.get(QueuedPost, r.json()["post_id"])
    assert post.status == PostStatus.QUEUED and post.source == "plan" and post.approved_at is None
    item = db.get(ContentPlanItem, item_id)
    assert item.status == "drafted" and item.queued_post_id == post.id
    assert "ANGLE" in seen["user"] and "Lead with [your number]" in seen["user"]
    assert "AUTHOR'S FACTS" in seen["user"] and "(none given)" in seen["user"]
    assert client.post(f"/api/plan/items/{item_id}/draft").status_code == 400


def test_skip_toggles_and_update_validates(client, db, soul, fake_llm):
    fake_llm["json"]["plan_week"] = {"posts": [_post("Retention — flows, offers, LTV", f"F{n}", topic=f"T{n}") for n in (1, 3, 5)]}
    plan = client.post("/api/plan/week", json={"count": 3}).json()["plan"]
    item_id = plan["items"][1]["id"]
    assert client.post(f"/api/plan/items/{item_id}/skip").json()["item"]["status"] == "skipped"
    assert client.post(f"/api/plan/items/{item_id}/skip").json()["item"]["status"] == "planned"
    assert client.post(f"/api/plan/items/{item_id}", json={"formula_id": "F42"}).status_code == 400
    ok = client.post(f"/api/plan/items/{item_id}", json={"topic": "New topic", "formula_id": "f12"})
    assert ok.json()["item"]["topic"] == "New topic" and ok.json()["item"]["formula_id"] == "F12"


def test_plan_page_renders(client, soul):
    html = client.get("/plan").text
    assert "Plan a new week" in html and 'href="/plan"' in html


# ── Learn my voice ────────────────────────────────────────────

SAMPLES = "\n---\n".join([
    "March 3. We cut our onboarding call from 60 to 25 minutes.. clients asked better questions in week one. "
    "The trick was a 3-page brief sent two days before the call.",
    "Most flows fail in the first email, not the fifth. I audited 40 welcome series last quarter and 31 of them "
    "buried the offer below three paragraphs of brand story.",
    "We raised prices 30% in May. Two clients left. Revenue went up anyway, and the team finally had time to do "
    "the work properly instead of chasing volume.",
])


def test_learn_voice_keeps_only_real_signature_lines(client, soul, fake_llm):
    fake_llm["json"]["learn_voice"] = {
        "voice_and_tone": "- Plain and direct\n- Speaks from client work",
        "fingerprint": "- Opens with a date or a number\n- Uses '..' as a soft pause",
        "never_use": "- No hashtags\n- No questions as openers",
        "signature_lines": ["Most flows fail in the first email, not the fifth.",
                            "Retention is a product problem wearing a marketing costume."],
    }
    r = client.post("/api/brand/learn-voice", json={"text": SAMPLES})
    assert r.status_code == 200, r.text
    body = r.json()
    sections = {s["title"]: s for s in body["sections"]}
    assert body["samples"] == 3 and body["dropped_lines"] == 1
    assert sections["Signature Lines"]["proposed"] == '- "Most flows fail in the first email, not the fifth."'
    assert "Opens with a date" in sections["Voice Fingerprint"]["proposed"]
    assert "current" in sections["My LinkedIn Voice & Tone"]


def test_learn_voice_needs_three_samples(client, soul, fake_llm):
    r = client.post("/api/brand/learn-voice", json={"text": "Just one short post."})
    assert r.status_code == 400 and "at least 3" in r.json()["error"]


def test_split_samples():
    from studio.voice import split_samples
    assert len(split_samples("a\n---\nb\n\n\n\nc")) == 3
