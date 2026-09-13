"""Engage: draft comment options for someone else's post (templates T1–T7)."""

from typing import Literal

from pydantic import BaseModel, Field

import llm
from content.humanizer import audit, auto_fix
from linkedin.url_parser import parse_linkedin_url

REACTIONS = ("LIKE", "PRAISE", "EMPATHY", "INTEREST", "APPRECIATION", "ENTERTAINMENT")
TEMPLATE_NAMES = {
    "T1": "Missing piece", "T2": "Answer the closing question", "T3": "Data first",
    "T4": "Practitioner observation", "T5": "Counter with concession", "T6": "Quotable reframe",
    "T7": "Sharper question",
}

COMMENT_RULES = """You draft comments on other people's LinkedIn posts for the author in <brand_voice>, using comment-templates.md (T1–T7) and voice-rules.md.

Each option:
- is 200–350 characters in 1–2 short paragraphs (12+ words);
- references one specific point from the post;
- adds one insight, number or experience the post didn't cover, and only experiences the brand profile supports;
- ends with a genuine question or a sharper angle;
- never pitches the author's product; no hashtags, no em dashes, no "Great post".
Every option uses a different template. If the post is spam, engagement bait or about a tragedy where a
comment would be tone-deaf, say so in skip_reason."""


class CommentOption(BaseModel):
    template: str = Field(description="Template code, T1-T7")
    text: str


class CommentDrafts(BaseModel):
    options: list[CommentOption]
    reaction: Literal["LIKE", "PRAISE", "EMPATHY", "INTEREST", "APPRECIATION", "ENTERTAINMENT"]
    skip_reason: str = Field(description="Empty unless the post should not get a comment")


def check_text(text: str, kind: str = "comment") -> tuple[str, dict]:
    """Safe auto-fixes plus the quality audit for a comment or reply."""
    fixed, _ = auto_fix(text.strip(), kind)
    return fixed, audit(fixed, kind)


def option_dict(code: str, text: str, kind: str = "comment", names: dict = TEMPLATE_NAMES) -> dict:
    code = (code or "").strip().upper()[:2]
    fixed, report = check_text(text, kind)
    return {"template": code if code in names else "", "template_name": names.get(code, kind.title()),
            "text": fixed, "report": report}


def draft_comment(post_text: str, post_url: str = "", author: str = "", count: int = 3) -> dict:
    """Two or three comment options plus a suggested reaction. Nothing is saved or posted."""
    post_text = (post_text or "").strip()
    if len(post_text) < 20:
        raise ValueError("Paste the post's text so the comment can respond to what it says")
    by = f" by {author.strip()}" if author.strip() else ""
    user = (f"Draft {count} comment options on this LinkedIn post{by}, each using a different template.\n\n"
            f"{llm.untrusted(post_text[:4000], 'linkedin_post')}")
    result = llm.complete_json("engage_comment", user, CommentDrafts, packs=("comment",),
                               instructions=COMMENT_RULES, effort="medium")
    options = [option_dict(o.template, o.text) for o in result.options[:count] if o.text.strip()]
    parsed = parse_linkedin_url(post_url) if post_url else {}
    return {"options": options, "reaction": result.reaction, "skip_reason": result.skip_reason.strip(),
            "post_urn": parsed.get("post_urn")}
