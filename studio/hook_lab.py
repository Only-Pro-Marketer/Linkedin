"""Hook Lab: explain why a post's opening works and turn it into a reusable template."""

from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import llm
from content.hook_library import _classify_hook_type, _extract_hook_text
from content.humanizer import audit
from content.templates.formulas import BY_ID, FORMULAS
from database.models import HookEntry

MAX_POST_CHARS = 6000
OPENER_RULES = {"question_opener", "cliche_opener", "stop_start_opener", "announcement_opener",
                "sincerity_opener", "all_caps_opener"}


class HookAnalysis(BaseModel):
    hook: str = Field(description="The post's opening line (or first two lines if line one is a fragment), copied exactly")
    formula_id: str = Field(description="Closest formula id from the list (F1-F20), or 'none'")
    confidence: Literal["high", "medium", "low"]
    why_it_works: str = Field(description="1-2 sentences on the mechanism that makes readers stop scrolling")
    template: str = Field(description="The hook as a reusable fill-in template with {placeholders}")
    better_version: str = Field(description="A stronger version if the hook breaks a reach rule, else an empty string")


def formula_catalog() -> str:
    return "\n".join(f"{f.id} {f.name}: {f.best_for}" for f in FORMULAS)


def analyze_hook(text: str) -> dict:
    """Classify a post's hook against F1–F20 and extract a fill-in template."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Paste a post to analyze")
    text = text[:MAX_POST_CHARS]
    prompt = f"""Classify the opening of this LinkedIn post against the hook formulas and explain why it works.

FORMULAS:
{formula_catalog()}

POST:
{llm.untrusted(text, "linkedin_post")}

Rules:
- Copy the hook exactly as written.
- formula_id is the closest match, or "none". Use confidence "low" for a loose fit.
- The template keeps the structure and swaps specifics for {{placeholders}} such as {{number}}, {{timeframe}}, {{category}}.
- If the hook breaks a 2026 reach rule (opens with a question, "Here's what…", an announcement, a cliché), write a
  better_version that keeps its idea. Otherwise better_version is an empty string."""
    result = llm.complete_json("studio_hook", prompt, HookAnalysis, packs=("hook",), brand=False)

    formula = BY_ID.get(result.formula_id.strip().upper())
    hook = result.hook.strip() or _extract_hook_text(text)
    report = audit(text, "post")
    flags = [i["message"] for i in report["blockers"] + report["warnings"] if i["id"] in OPENER_RULES]
    return {
        "hook": hook,
        "formula": ({"id": formula.id, "name": formula.name, "why": formula.why, "goals": list(formula.goals)}
                    if formula else None),
        "confidence": result.confidence,
        "why_it_works": result.why_it_works.strip(),
        "template": result.template.strip(),
        "better_version": result.better_version.strip(),
        "hook_type": _classify_hook_type(hook),
        "reach_flags": flags,
    }


def save_hook(db: Session, hook: str, template: str = "", formula_id: str | None = None,
              topic: str = "") -> HookEntry:
    """Store an analyzed hook in the hook library so generation can reuse it."""
    hook = (hook or "").strip()
    if not hook:
        raise ValueError("Nothing to save")
    entry = HookEntry(
        text=hook[:1000],
        hook_type=_classify_hook_type(hook),
        source="hook_lab",
        formula_id=formula_id if formula_id in BY_ID else None,
        template_text=(template or "").strip()[:2000] or None,
        topic_category=topic or None,
        engagement_score=0,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
