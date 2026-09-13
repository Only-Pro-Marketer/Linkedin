"""Studio Write: goal → formula → draft, using only facts the author supplies."""

import re
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import llm
from content.pipeline import create_queued_post, prepare_text, repair_if_needed
from content.prompt_builder import OUTPUT_ONLY, WRITING_RULES
from content.templates.formulas import BY_ID, FORMULAS, Formula, formulas_for_goal
from database.models import QueuedPost

GOAL_INFO = {
    "comments": {"label": "Start a conversation",
                 "desc": "Invites replies from people with their own experience. Comments carry the most weight in reach."},
    "saves": {"label": "Be worth saving",
              "desc": "A framework, checklist or breakdown people bookmark to use later."},
    "reposts": {"label": "Get shared",
                "desc": "A clear stance or a shift people want to pass on to their network."},
    "likes": {"label": "Build goodwill",
              "desc": "A relatable story or an honest moment people nod along to."},
}
RECENT_DAYS = 7
SHORTLIST_SIZE = 4
_WORD = re.compile(r"[a-z]{4,}")


def formula_dict(f: Formula, used_recently: bool = False) -> dict:
    return {"id": f.id, "name": f.name, "goals": list(f.goals), "best_for": f.best_for, "why": f.why,
            "caveat": f.caveat, "needs": list(f.needs), "skeleton": f.skeleton, "used_recently": used_recently}


def recently_used(db: Session) -> set[str]:
    since = datetime.utcnow() - timedelta(days=RECENT_DAYS)
    rows = (db.query(QueuedPost.formula_id)
            .filter(QueuedPost.formula_id.isnot(None), QueuedPost.created_at >= since)
            .distinct().all())
    return {r[0] for r in rows}


def shortlist_formulas(db: Session, goal: str, topic: str = "", limit: int = SHORTLIST_SIZE) -> list[dict]:
    """Formulas for the goal: topic matches first, anything used in the last week last."""
    used = recently_used(db)
    topic_words = set(_WORD.findall((topic or "").lower()))
    candidates = formulas_for_goal(goal) or FORMULAS

    def rank(item):
        index, f = item
        overlap = len(topic_words & set(_WORD.findall(f"{f.name} {f.best_for}".lower())))
        return (f.id in used, -overlap, index)

    ordered = [f for _, f in sorted(enumerate(candidates), key=rank)]
    return [formula_dict(f, f.id in used) for f in ordered[:limit]]


def build_write_prompt(topic: str, goal: str, formula: Formula | None, notes: str, angle: str = "") -> str:
    info = GOAL_INFO.get(goal, GOAL_INFO["comments"])
    parts = [f"Write one LinkedIn post about: {topic.strip()}",
             f"GOAL: {info['label']}. {info['desc']}"]
    if formula:
        caveat = f"\nWatch out: {formula.caveat}" if formula.caveat else ""
        parts.append(f"FORMULA: {formula.label}\nWhy it works: {formula.why}{caveat}\n"
                     f"SKELETON (adapt it to the topic; never leave its {{braces}} in the post):\n{formula.skeleton}")
    if angle.strip():
        parts.append(f"ANGLE (direction only, not a source of facts): {angle.strip()}")
    parts.append("AUTHOR'S FACTS (with the brand profile, the only personal facts you may use):\n"
                 + (notes.strip() or "(none given)"))
    parts.append(
        "FACT RULES:\n"
        "- Never invent numbers, clients, dates, quotes or results.\n"
        "- If the formula needs a fact the author did not give, write a short bracketed placeholder such as "
        "[your number] or [client type] so the author can fill it in.\n"
        "- Opinions and observations are fine without facts."
    )
    parts.append(WRITING_RULES)
    parts.append(OUTPUT_ONLY)
    return "\n\n".join(parts)


def draft_post(db: Session, topic: str, goal: str, formula_id: str | None = None, notes: str = "",
               angle: str = "") -> dict:
    """Draft a post and run it through the quality checks. Nothing is queued."""
    formula = BY_ID.get((formula_id or "").strip().upper())
    if formula is None:
        picks = shortlist_formulas(db, goal, topic, limit=1)
        formula = BY_ID[picks[0]["id"]] if picks else None
    prompt = build_write_prompt(topic, goal, formula, notes, angle)
    raw = llm.complete("studio_write", prompt, packs=("post", "formulas"), max_tokens=4000).text
    text, report, changes = prepare_text(raw, topic)
    text, report, repaired = repair_if_needed(text, report, topic)
    return {"text": text, "report": report, "changes": changes, "repaired": repaired, "goal": goal,
            "formula": formula_dict(formula) if formula else None}


def save_to_queue(db: Session, text: str, *, topic: str = "", goal: str | None = None,
                  formula_id: str | None = None, source: str = "studio") -> QueuedPost:
    """Queue the user's (possibly edited) draft. The AI never rewrites it at this point."""
    formula = BY_ID.get(formula_id or "")
    first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")
    return create_queued_post(
        db, text, topic=(topic or first_line)[:200], source=source,
        template_name=formula.label if formula else "Studio draft",
        formula_id=formula.id if formula else None, goal=goal, auto_repair=False,
    )
