"""The one path every new post takes before it reaches the review queue.

format → safe auto-fix → quality audit → (one AI repair if blockers remain)
→ structure analysis → fact-check + reach score (one AI call) → save QUEUED.

Every creator (auto batch, Idea Lab, Studio, Plan, recycler, research,
competitor recreate, autoresearch) calls create_queued_post().
"""

import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

import llm
from config import settings
from content.humanizer import audit, auto_fix
from content.post_formatter import format_for_linkedin
from content.quality_rules import POST
from database.models import PostStatus, QueuedPost, ResearchItem
from existing_tool.post_analyzer import PostAnalyzer

logger = logging.getLogger(__name__)


def prepare_text(raw: str, topic: str = "", kind: str = POST) -> tuple[str, dict, list[str]]:
    """Format (posts only), auto-fix and audit. No AI call."""
    text = format_for_linkedin(raw, topic) if kind == POST else (raw or "").strip()
    text, changes = auto_fix(text, kind)
    return text, audit(text, kind), changes


def repair_if_needed(text: str, report: dict, topic: str = "", kind: str = POST) -> tuple[str, dict, bool]:
    """One AI repair pass when blockers remain; keep it only if it is better."""
    if not report["blockers"] or not settings.AUTO_REPAIR:
        return text, report, False
    from content.ai_fix import fix_with_ai
    try:
        fixed_raw = fix_with_ai(text, report, kind)
    except llm.LLMError as e:
        logger.info("AI repair skipped: %s", e)
        return text, report, False
    fixed, fixed_report, _ = prepare_text(fixed_raw, topic, kind)
    if (len(fixed_report["blockers"]), -fixed_report["score"]) < (len(report["blockers"]), -report["score"]):
        return fixed, fixed_report, True
    return text, report, False


def quality_payload(report: dict, changes: list[str] | None = None, repaired: bool = False) -> str:
    data = {k: report[k] for k in ("score", "status", "blockers", "warnings", "tips", "stats")}
    data["auto_fixes"] = changes or []
    data["ai_repaired"] = repaired
    return json.dumps(data)


def refresh_quality(post: QueuedPost) -> dict:
    """Re-audit a stored post after the user edits it (no AI call)."""
    report = audit(post.content or "", POST)
    post.quality_score = report["score"]
    post.quality_report = quality_payload(report)
    return report


def create_queued_post(
    db: Session,
    raw_text: str,
    *,
    topic: str,
    source: str,
    template_name: str | None = None,
    research_context: str = "",
    generation_prompt: str | None = None,
    research_item_id: int | None = None,
    recycled_from_id: int | None = None,
    formula_id: str | None = None,
    goal: str | None = None,
    review: bool = True,
    virality: dict | None = None,
    auto_repair: bool = True,
) -> QueuedPost:
    """Run the full quality pipeline and save the post as QUEUED."""
    content, report, changes = prepare_text(raw_text, topic)
    repaired = False
    if auto_repair:
        content, report, repaired = repair_if_needed(content, report, topic)

    structure = PostAnalyzer().analyze(content)

    fact = None
    if review:
        from content.review import review_post
        fact, virality = review_post(content, topic, research_context)

    post = QueuedPost(
        content=content,
        hook=structure.hook,
        hook_type=structure.hook_type.value,
        body_format=structure.body_format.value,
        cta_type=structure.cta_type.value,
        template_name=template_name,
        word_count=structure.word_count,
        status=PostStatus.QUEUED,
        topic=(topic or "")[:200],
        research_context=research_context or None,
        research_item_id=research_item_id,
        generation_prompt=generation_prompt,
        recycled_from_id=recycled_from_id,
        source=source,
        formula_id=formula_id,
        goal=goal,
        quality_score=report["score"],
        quality_report=quality_payload(report, changes, repaired),
    )
    if fact:
        post.fact_check_status = fact["verdict"]
        post.fact_check_notes = json.dumps(fact)
        post.fact_checked_at = datetime.utcnow()
    if virality:
        post.virality_score = virality.get("total_score")
        post.virality_breakdown = json.dumps(virality)
        post.virality_performance = virality.get("predicted_performance")

    db.add(post)
    db.commit()
    db.refresh(post)

    if research_item_id:  # research is consumed only once a post exists
        item = db.get(ResearchItem, research_item_id)
        if item and not item.used:
            item.used = True
            db.commit()

    logger.info("Queued post #%s (%s): quality %s/100 %s%s", post.id, source, report["score"],
                report["status"], " (AI-repaired)" if repaired else "")
    return post
