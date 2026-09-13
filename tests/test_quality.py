"""Phase 2: quality engine, auto-fix, pipeline, templates and formulas."""

import json
import re

import pytest

from content.humanizer import audit, auto_fix
from tests.conftest import DEFAULT_FAKE_POST

REVIEW = {
    "fact_verdict": "pass", "fact_issues": [], "fact_summary": "Nothing invented.",
    "hook_power": 20, "structure": 16, "value_insight": 15, "engagement_trigger": 12,
    "authenticity": 8, "relevance": 7, "strengths": ["specific numbers"], "improvements": [],
    "one_line_verdict": "Solid, specific post.",
}


def ids(report, bucket="blockers"):
    return {i["id"] for i in report[bucket]}


def test_clean_post_passes():
    report = audit(DEFAULT_FAKE_POST)
    assert report["blockers"] == []
    assert report["status"] in ("ready", "review")


@pytest.mark.parametrize("text, rule", [
    ("Ever wondered why your ads stop working?\n\nWe spent $4,000 in March.", "question_opener"),
    ("In today's market, growth is hard.\n\nWe spent $4,000 in March.", "cliche_opener"),
    ("Stop posting every day.\n\nWe spent $4,000 in March.", "stop_start_opener"),
    ("I'm excited to announce our new office.\n\nIt has 12 desks.", "announcement_opener"),
    ("We grew 41% in March.\n\nThe team did it.\n\nWhat do you think?", "generic_closer"),
    ("We grew 41% in March.\n\nThe result? A calmer team.", "reveal_bridge"),
    ("We grew 41% in March.\n\nIt's not about the tool, it's about the habit.", "neg_parallel"),
    ("We grew 41% in March.\n\nFull write-up at https://example.com/post", "body_link"),
    ("I lost [DOLLAR_AMOUNT] on ads last year.", "placeholder"),
    ("We grew 41% in March.\n\nComment YES below and I'll send the checklist.", "engagement_bait"),
    ("THIS CHANGED EVERYTHING.\n\nWe grew 41% in March.", "all_caps_opener"),
])
def test_blocker_rules(text, rule):
    assert rule in ids(audit(text))


def test_dense_paragraph_is_flagged():
    text = "We grew 41% in March.\n\nLeveraging robust insights, we streamlined a comprehensive landscape."
    assert "dense_paragraph" in ids(audit(text))


def test_em_dash_cap_and_autofix():
    text = "We shipped it — finally — after 3 weeks — and it held up — mostly.\n\nThe next release is on May 4."
    assert "em_dashes" in ids(audit(text))
    fixed, changes = auto_fix(text)
    assert fixed.count("—") <= 1 and changes
    assert "em_dashes" not in ids(audit(fixed))


def test_autofix_is_safe_and_idempotent():
    messy = ("Let me be honest: we lost the client on 14 Feb.\n\nThe result? We rebuilt onboarding in 9 days.\n\n"
             "“Quotes” -- here.\n\nWe utilized 3 tools and leveraged a checklist.")
    once, changes = auto_fix(messy)
    twice, changes2 = auto_fix(once)
    assert once == twice and changes2 == []
    assert "Let me be honest" not in once and "The result?" not in once
    assert "“" not in once and "--" not in once
    assert "used 3 tools" in once and "used a checklist" in once
    assert once.startswith("We lost the client on 14 Feb.")
    assert "14 Feb" in once and "9 days" in once  # facts untouched


def test_comment_rules():
    report = audit("Great post! Totally agree.", "comment")
    assert "generic_praise" in ids(report)
    assert "short" in ids(report, "warnings")


def test_quality_api(client):
    r = client.post("/api/quality/check", json={"text": "Thoughts?", "kind": "post"})
    assert r.status_code == 200 and r.json()["status"] == "fix"
    r = client.post("/api/quality/autofix", json={"text": "We shipped -- finally.", "kind": "post"})
    assert r.json()["text"] == "We shipped, finally."


def test_ai_fix_endpoint(client, fake_llm):
    fake_llm["text"]["ai_fix"] = DEFAULT_FAKE_POST
    r = client.post("/api/quality/ai-fix", json={"text": "Ever wondered why?\n\nNo numbers here.", "kind": "post"})
    assert r.status_code == 200 and r.json()["changed"] is True
    assert r.json()["audit"]["blockers"] == []


# ── Pipeline ──────────────────────────────────────────────────

def test_pipeline_saves_quality_and_review(db, fake_llm):
    from content.pipeline import create_queued_post
    fake_llm["json"]["post_review"] = REVIEW
    post = create_queued_post(db, DEFAULT_FAKE_POST, topic="onboarding", source="studio")
    assert post.status.value == "queued" and post.source == "studio"
    assert post.quality_score is not None and json.loads(post.quality_report)["status"] in ("ready", "review")
    assert post.fact_check_status == "pass" and post.virality_score
    assert "ai_fix" not in fake_llm["calls"]


def test_pipeline_repairs_blockers_once(db, fake_llm):
    from content.pipeline import create_queued_post
    fake_llm["json"]["post_review"] = REVIEW
    fake_llm["text"]["ai_fix"] = DEFAULT_FAKE_POST
    post = create_queued_post(db, "Ever wondered why onboarding drags?\n\nIt does.", topic="onboarding", source="auto")
    assert post.content.startswith("I cut our onboarding call")
    assert json.loads(post.quality_report)["ai_repaired"] is True
    assert fake_llm["calls"].count("ai_fix") == 1


def test_generate_batch_end_to_end(db, fake_llm):
    from content.generator import ContentGenerator
    fake_llm["json"]["post_review"] = REVIEW
    posts = ContentGenerator(db).generate_batch(count=2)
    assert len(posts) == 2
    assert all(p.quality_score is not None and p.source == "auto" for p in posts)
    assert fake_llm["calls"].count("generate") == 2


def test_research_is_used_only_after_saving(db, fake_llm):
    from content.generator import ContentGenerator
    from database.models import ResearchItem
    item = ResearchItem(source="rss", topic="Shopify checkout update", title="Checkout", content=None,
                        relevance_score=0.9, used=False)
    db.add(item)
    db.commit()
    fake_llm["json"]["post_review"] = REVIEW
    fake_llm["text"]["generate"] = ""  # generation "fails" → research must stay unused
    gen = ContentGenerator(db)
    gen._call_claude = lambda prompt, feature="generate": None
    assert gen.generate_batch(count=1) == []
    db.refresh(item)
    assert item.used is False
    db.delete(item)
    db.commit()


# ── Templates & formulas ──────────────────────────────────────

BANNED = [r"(?im)^\s*stop \w+", r"(?im)^the \w+\?", r"(?im)^here'?s ", r"(?i)agree or disagree",
          r"(?im)^\w+\.$", r"(?i)follow (me )?for more", r"(?i)what do you think"]


def test_builtin_templates_avoid_banned_devices():
    from content.templates.template_library import BUILTIN_TEMPLATES
    for t in BUILTIN_TEMPLATES:
        text = "\n".join([t.hook_pattern, t.body_pattern, t.cta_pattern])
        for pattern in BANNED:
            assert not re.search(pattern, text), f"{t.name}: {pattern}"
        assert t.cta_pattern.rstrip().endswith("?"), t.name


def test_twenty_formulas_and_rotation():
    from content.templates.formulas import BY_ID, FORMULAS
    from content.templates.template_library import get_all_templates, get_template_by_name
    assert len(FORMULAS) == 20 and set(BY_ID) == {f"F{i}" for i in range(1, 21)}
    assert get_template_by_name("F7 Odd-Precision Money Ledger") is not None
    rotation = {t.name for t in get_all_templates()}
    assert "F10 Contrarian + Historical Receipts" in rotation
    assert "F7 Odd-Precision Money Ledger" not in rotation  # needs real numbers → Studio only
    assert not any("supplement" in t.hook_pattern.lower() for t in get_all_templates())
