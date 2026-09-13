"""Studio Repurpose: find up to three post angles in long-form content and draft each one."""

from pydantic import BaseModel, Field

import llm
from content.pipeline import prepare_text
from content.prompt_builder import WRITING_RULES
from content.templates.formulas import BY_ID, FORMULAS
from studio.writer import GOAL_INFO, formula_dict

SOURCE_TYPES = {
    "article": "Article or blog post",
    "newsletter": "Newsletter issue",
    "transcript": "Podcast or video transcript",
    "notes": "My rough notes",
    "post": "A long post from another platform",
}
MIN_SOURCE_CHARS = 200
MAX_SOURCE_CHARS = 60000
MAX_ANGLES = 3


class Angle(BaseModel):
    angle: str = Field(description="The one idea this post takes from the source, in under 12 words")
    formula_id: str = Field(description="Formula id from the list that fits this angle, or 'none'")
    post: str = Field(description="The finished LinkedIn post text")


class RepurposeResult(BaseModel):
    angles: list[Angle]


def repurpose(source_text: str, source_type: str = "article", goal: str = "saves") -> dict:
    """Draft up to three standalone posts from one source. Nothing is queued."""
    source = (source_text or "").strip()[:MAX_SOURCE_CHARS]
    if len(source) < MIN_SOURCE_CHARS:
        raise ValueError(f"Paste at least {MIN_SOURCE_CHARS} characters of source material")
    label = SOURCE_TYPES.get(source_type, "source material")
    info = GOAL_INFO.get(goal, GOAL_INFO["saves"])
    if source_type == "notes":
        voice = "These are the author's own notes, so write in first person from their experience."
    else:
        voice = ("The source may be someone else's work. Write from the author's point of view (what they took "
                 "from it, or how it applies to their audience) and never present its experiences as the author's.")
    catalog = "\n".join(f"{f.id} {f.name}: {f.best_for}" for f in FORMULAS)
    prompt = f"""Turn this {label.lower()} into up to {MAX_ANGLES} separate LinkedIn posts, each built on a different angle.

GOAL: {info['label']}. {info['desc']}

FORMULAS (pick the best fit for each angle):
{catalog}

SOURCE:
{llm.untrusted(source, source_type)}

Rules:
- Each post stands alone and develops one idea from the source. Don't summarize the whole piece.
- Keep facts, numbers and names exactly as the source states them. Never add new ones.
- {voice}
- Links belong in the first comment, never in the post.

{WRITING_RULES}"""
    result = llm.complete_json("studio_repurpose", prompt, RepurposeResult, packs=("post", "formulas"),
                               effort=None, max_tokens=12000)
    angles = []
    for a in result.angles[:MAX_ANGLES]:
        text, report, changes = prepare_text(a.post, a.angle)
        if not text.strip():
            continue
        formula = BY_ID.get(a.formula_id.strip().upper())
        angles.append({"angle": a.angle.strip(), "formula": formula_dict(formula) if formula else None,
                       "text": text, "report": report, "changes": changes})
    if not angles:
        raise llm.LLMError("Claude couldn't find a post angle in this source. Try a longer or more specific piece.")
    return {"angles": angles, "goal": goal}
