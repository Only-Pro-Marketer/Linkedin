"""Plan: a 3–5 post week across the user's pillars, then "Draft this" per item.

The guardrails from pillars-framework.md are enforced in code, not only asked
for: no pillar above 60% of the week, no formula used twice within 7 days.
"""

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import llm
from content.brand import get_niche, get_pillars
from content.pipeline import create_queued_post
from content.templates.formulas import BY_ID, FORMULAS, formulas_for_goal
from database.models import ContentPlan, ContentPlanItem, QueuedPost
from post_queue.slots import next_calendar_slots
from studio.writer import draft_post, recently_used
from utils.timeutil import local_now, posting_tz

MIN_POSTS, MAX_POSTS = 3, 5
MAX_PILLAR_SHARE = 0.6
FALLBACK_PILLARS = [
    "Expertise — how-tos, frameworks and lessons from the work",
    "Story — what happened, what it cost, what changed",
    "Point of view — where the industry gets it wrong",
]


class PlannedPost(BaseModel):
    pillar: str = Field(description="One of the pillars, copied exactly")
    goal: Literal["comments", "reposts", "likes", "saves"]
    formula_id: str = Field(description="Formula id, F1-F20")
    topic: str = Field(description="What the post is about, specific enough to write today")
    angle: str = Field(description="One-line direction: the claim, story beat or question to lead with")


class WeekPlan(BaseModel):
    posts: list[PlannedPost]


def violations(posts: list[PlannedPost], recent: set[str]) -> list[str]:
    notes = []
    counts = Counter(p.pillar.strip() for p in posts)
    for pillar, n in counts.items():
        if len(posts) >= MIN_POSTS and n / len(posts) > MAX_PILLAR_SHARE:
            notes.append(f'"{pillar}" has {n} of {len(posts)} posts (keep each pillar at or under 60%)')
    seen = set()
    for p in posts:
        fid = p.formula_id.strip().upper()
        if fid in seen:
            notes.append(f"{fid} is used twice this week")
        elif fid in recent:
            notes.append(f"{fid} was already used in the last 7 days")
        seen.add(fid)
    return notes


def fix_formulas(posts: list[PlannedPost], recent: set[str]) -> list[str]:
    """Swap repeated, recently used or unknown formulas for fresh ones that fit the goal."""
    used, fixes = set(recent), []
    for p in posts:
        fid = p.formula_id.strip().upper()
        if fid in BY_ID and fid not in used:
            p.formula_id = fid
            used.add(fid)
            continue
        fresh = [f for f in formulas_for_goal(p.goal) if f.id not in used] or [f for f in FORMULAS if f.id not in used]
        if fresh:
            fixes.append(f"{fid or 'missing'} → {fresh[0].id} for “{p.topic[:50]}”")
            p.formula_id = fresh[0].id
            used.add(fresh[0].id)
    return fixes


def build_prompt(count: int, pillars: list[str], focus: str, recent: set[str], feedback: str = "") -> str:
    catalog = "\n".join(f"{f.id} {f.name} (goals: {', '.join(f.goals)}): {f.best_for}" for f in FORMULAS)
    pillar_lines = "\n".join(f"- {p}" for p in pillars)
    avoid = f" None of these, used in the last 7 days: {', '.join(sorted(recent))}." if recent else ""
    parts = [
        f"Plan {count} LinkedIn posts for the coming week for the author in the brand profile ({get_niche()}).",
        f"PILLARS (copy the names exactly):\n{pillar_lines}",
    ]
    if focus.strip():
        parts.append(f"FOCUS THIS WEEK: {focus.strip()}")
    parts.append(f"FORMULAS:\n{catalog}")
    parts.append(
        "Rules:\n"
        "- Spread the posts across pillars; no pillar gets more than 60% of them.\n"
        f"- Every post uses a different formula.{avoid}\n"
        "- Mix goals, with at least one post aimed at comments.\n"
        "- Topics are specific and only use experiences the brand profile supports; otherwise make them "
        "observations, how-tos or opinions.\n"
        "- Angles give direction only. Never invent numbers, clients or results in them; write [your number] "
        "where a real figure would help.\n"
        "- List the posts in the order they should go out."
    )
    if feedback:
        parts.append(f"YOUR PREVIOUS PLAN BROKE THESE RULES. FIX THEM:\n{feedback}")
    return "\n\n".join(parts)


def _ask(prompt: str) -> list[PlannedPost]:
    return llm.complete_json("plan_week", prompt, WeekPlan, packs=("plan",), effort="medium", max_tokens=8000).posts


def slot_label(slot_utc: datetime | None) -> str:
    if not slot_utc:
        return "Unscheduled"
    local = slot_utc.replace(tzinfo=timezone.utc).astimezone(posting_tz())
    return f"{local:%a, %b} {local.day} · {local.strftime('%I:%M %p').lstrip('0')}"


def plan_week(db: Session, count: int = 4, focus: str = "") -> ContentPlan:
    """Ask Claude for a week, enforce the guardrails, and map posts onto calendar slots."""
    count = max(MIN_POSTS, min(MAX_POSTS, int(count)))
    pillars = get_pillars() or FALLBACK_PILLARS
    recent = recently_used(db)

    posts = _ask(build_prompt(count, pillars, focus, recent))[:count]
    problems = violations(posts, recent)
    if problems:
        retry = _ask(build_prompt(count, pillars, focus, recent, "\n".join(problems)))[:count]
        if len(retry) >= MIN_POSTS:
            posts = retry
    if not posts:
        raise llm.LLMError("Claude didn't return a plan. Try again.")

    fixes = fix_formulas(posts, recent)
    warnings = [f"Changed a formula to avoid a repeat: {x}" for x in fixes]
    warnings += [v for v in violations(posts, recent) if "60%" in v]

    slots = next_calendar_slots(db, count=len(posts), days=8)
    first = slots[0] if slots else local_now()
    plan = ContentPlan(week_start=first.strftime("%Y-%m-%d"), focus=focus.strip() or None,
                       warnings=json.dumps(warnings))
    for i, p in enumerate(posts):
        slot = slots[i].astimezone(timezone.utc).replace(tzinfo=None) if i < len(slots) else None
        plan.items.append(ContentPlanItem(slot_at=slot, pillar=p.pillar.strip()[:200], goal=p.goal,
                                          formula_id=p.formula_id, topic=p.topic.strip(), angle=p.angle.strip()))
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def draft_item(db: Session, item: ContentPlanItem) -> QueuedPost:
    """Write the planned post and put it in the Queue for review (never auto-approved)."""
    if item.status == "drafted" and item.queued_post_id:
        raise ValueError("This one is already in your Queue")
    result = draft_post(db, item.topic, item.goal, item.formula_id, notes="", angle=item.angle or "")
    formula = BY_ID.get(item.formula_id or "")
    post = create_queued_post(db, result["text"], topic=(item.topic or "")[:200], source="plan",
                              template_name=formula.label if formula else "Plan",
                              formula_id=item.formula_id, goal=item.goal, auto_repair=False)
    item.status, item.queued_post_id, item.error = "drafted", post.id, None
    db.commit()
    return post


def current_plan(db: Session) -> ContentPlan | None:
    return db.query(ContentPlan).order_by(ContentPlan.id.desc()).first()


def item_dict(item: ContentPlanItem) -> dict:
    from dashboard.common import to_iso
    formula = BY_ID.get(item.formula_id or "")
    return {
        "id": item.id, "slot_at": to_iso(item.slot_at), "slot_label": slot_label(item.slot_at),
        "pillar": item.pillar, "goal": item.goal, "formula_id": item.formula_id,
        "formula_name": formula.name if formula else "", "topic": item.topic, "angle": item.angle,
        "status": item.status, "queued_post_id": item.queued_post_id, "error": item.error,
    }


def plan_dict(plan: ContentPlan | None) -> dict | None:
    if not plan:
        return None
    items = sorted(plan.items, key=lambda i: (i.slot_at is None, i.slot_at or datetime.max, i.id))
    return {
        "id": plan.id, "week_start": plan.week_start, "focus": plan.focus,
        "warnings": json.loads(plan.warnings) if plan.warnings else [],
        "items": [item_dict(i) for i in items],
        "mix": dict(Counter(i.pillar for i in plan.items if i.status != "skipped")),
    }
