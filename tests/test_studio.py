"""Phase 4: Studio (Write, Repurpose, Hook Lab)."""

import llm
from database.models import HookEntry, PostStatus, QueuedPost, StudioRun
from tests.conftest import DEFAULT_FAKE_POST, make_post


def test_studio_page_renders(client):
    html = client.get("/studio").text
    assert "Hook Lab" in html and "Repurpose" in html and "F20" in html


def test_shortlist_matches_goal_and_skips_recent_formulas(client, db):
    from content.templates.formulas import BY_ID
    first = client.post("/api/studio/formulas", json={"goal": "comments"}).json()["formulas"]
    assert len(first) > 1 and all("comments" in BY_ID[f["id"]].goals for f in first)
    make_post(db, formula_id=first[0]["id"])
    again = client.post("/api/studio/formulas", json={"goal": "comments"}).json()["formulas"]
    assert first[0]["id"] not in [f["id"] for f in again]  # used this week → drops out of the top picks

    from studio.writer import shortlist_formulas
    full = shortlist_formulas(db, "comments", limit=50)
    assert full[-1]["id"] == first[0]["id"] and full[-1]["used_recently"] is True


def test_write_returns_checked_draft_without_queueing(client, db, fake_llm):
    r = client.post("/api/studio/write", json={"topic": "Shorter onboarding calls", "goal": "comments",
                                               "notes": "60 to 25 minutes in March"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"].startswith("I cut our onboarding call")
    assert body["report"]["status"] in ("ready", "review", "fix")
    assert body["formula"]["id"].startswith("F")
    assert "studio_write" in fake_llm["calls"]
    run = db.query(StudioRun).one()
    assert run.tool == "write" and run.error is None and body["run_id"] == run.id
    assert db.query(QueuedPost).count() == 0  # nothing is queued until the user saves


def test_write_prompt_carries_notes_and_formula(client, monkeypatch, fake_llm):
    seen = {}

    def complete(feature, user, **kw):
        if feature == "studio_write":  # ignore any follow-up repair call
            seen.update(user=user, packs=kw.get("packs"))
        return llm.LLMResult(DEFAULT_FAKE_POST, "fake", "end_turn", {})

    monkeypatch.setattr(llm, "complete", complete)
    client.post("/api/studio/write", json={"topic": "Pricing", "goal": "reposts", "formula_id": "F2",
                                           "notes": "Raised prices 30% in May"})
    assert "Raised prices 30% in May" in seen["user"] and "R.I.P." in seen["user"]
    assert "formulas" in seen["packs"]


def test_write_error_is_shown_and_recorded(client, db, monkeypatch):
    def boom(*a, **k):
        raise llm.LLMError("Claude is overloaded right now. Try again in a minute.")

    monkeypatch.setattr(llm, "complete", boom)
    r = client.post("/api/studio/write", json={"topic": "x", "goal": "comments"})
    assert r.status_code == 502 and "overloaded" in r.json()["error"]
    assert db.query(StudioRun).one().error.startswith("Claude is overloaded")


def test_write_requires_topic(client):
    assert client.post("/api/studio/write", json={"topic": "  "}).status_code == 400


def test_repurpose_returns_audited_angles(client, fake_llm):
    fake_llm["json"]["studio_repurpose"] = {"angles": [
        {"angle": "The 25-minute call", "formula_id": "F10", "post": DEFAULT_FAKE_POST},
        {"angle": "Weak one", "formula_id": "F99", "post": "In today's fast-paced world, posting matters.\n\nAgree?"},
    ]}
    r = client.post("/api/studio/repurpose", json={"source_text": "A long article paragraph. " * 20,
                                                   "source_type": "article", "goal": "saves"})
    assert r.status_code == 200, r.text
    angles = r.json()["angles"]
    assert len(angles) == 2
    assert angles[0]["formula"]["id"] == "F10" and angles[1]["formula"] is None
    assert angles[1]["report"]["blockers"]


def test_repurpose_needs_enough_source(client, fake_llm):
    assert client.post("/api/studio/repurpose", json={"source_text": "too short"}).status_code == 400


def test_hook_lab_analyze_and_save(client, db, fake_llm):
    fake_llm["json"]["studio_hook"] = {
        "hook": "Are you still posting every day?", "formula_id": "f5", "confidence": "medium",
        "why_it_works": "It calls out a habit.", "template": "Are you still {habit}?",
        "better_version": "I stopped posting daily in {month}.",
    }
    r = client.post("/api/studio/hook", json={"text": "Are you still posting every day?\n\nI stopped in May. Reach went up 40%."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["formula"]["id"] == "F5"
    assert body["reach_flags"], "a question opener should be flagged"
    s = client.post("/api/studio/hook/save", json={"hook": body["hook"], "template": body["template"], "formula_id": "F5"})
    assert s.status_code == 200
    entry = db.query(HookEntry).one()
    assert entry.formula_id == "F5" and entry.template_text == "Are you still {habit}?" and entry.source == "hook_lab"


def test_save_to_queue_keeps_the_users_text(client, db, fake_llm):
    r = client.post("/api/studio/save", json={"text": DEFAULT_FAKE_POST, "topic": "Onboarding", "goal": "comments",
                                              "formula_id": "F10", "source": "studio"})
    assert r.status_code == 200, r.text
    post = db.get(QueuedPost, r.json()["id"])
    assert post.status == PostStatus.QUEUED and post.source == "studio"
    assert post.formula_id == "F10" and post.goal == "comments"
    assert post.content.strip() == DEFAULT_FAKE_POST.strip()
    assert post.quality_report


def test_runs_endpoint_lists_history(client, fake_llm):
    client.post("/api/studio/write", json={"topic": "A topic", "goal": "saves"})
    runs = client.get("/api/studio/runs?tool=write").json()["runs"]
    assert runs and runs[0]["tool"] == "write" and runs[0]["created_at"].endswith("Z")
