"""Profile Optimizer: a 9-part scorecard with rewrites, using the profile playbooks in knowledge/."""

import re
from typing import Literal

from pydantic import BaseModel, Field

import llm

PARTS = [
    ("headline", "Headline"), ("about", "About"), ("experience", "Experience"), ("skills", "Skills"),
    ("featured", "Featured"), ("custom_url", "Custom URL"), ("recommendations", "Recommendations"),
    ("banner", "Banner"), ("photo", "Photo"),
]
HEADLINE_MAX = 220
ABOUT_MAX = 2600
SLUG_JUNK = re.compile(r"-[0-9a-f]{6,}$|\d{3,}$", re.I)


class PartScore(BaseModel):
    part: Literal["headline", "about", "experience", "skills", "featured", "custom_url", "recommendations",
                  "banner", "photo"]
    score: int = Field(description="0-10")
    verdict: str = Field(description="One sentence on what works or what doesn't")
    fix: str = Field(description="The single most useful change, concrete")


class ProfileReview(BaseModel):
    parts: list[PartScore]
    headline_options: list[str] = Field(description="3 rewritten headlines, each under 220 characters")
    about_rewrite: str = Field(description="About section rewritten with the 7-step structure; empty if none was given")
    experience_bullets: list[str] = Field(description="Up to 5 rewritten bullets for the most recent role; empty if none")
    top_priority: str = Field(description="The one change that would help most, in one sentence")


def _url_check(url: str) -> tuple[int, str, str] | None:
    m = re.search(r"linkedin\.com/in/([^/?#]+)", url or "", re.I)
    if not m:
        return None
    slug = m.group(1)
    if SLUG_JUNK.search(slug):
        return (4, f"Your URL ends in random characters ({slug}).",
                "Set a clean custom URL: Me → View profile → Edit public profile & URL.")
    return (10, f"Clean custom URL ({slug}).", "Nothing to change.")


def optimize_profile(data: dict) -> dict:
    """Score all 9 parts; deterministic checks override the model where they can."""
    headline = (data.get("headline") or "").strip()
    about = (data.get("about") or "").strip()
    if not headline and not about:
        raise ValueError("Paste at least your headline or your About section")
    url = (data.get("profile_url") or "").strip()
    recs = data.get("recommendations")
    fields = [
        f"HEADLINE: {headline or '(not given)'}",
        f"ABOUT:\n{about or '(not given)'}",
        f"EXPERIENCE (most recent role):\n{(data.get('experience') or '').strip() or '(not given)'}",
        f"SKILLS: {(data.get('skills') or '').strip() or '(not given)'}",
        f"FEATURED: {(data.get('featured') or '').strip() or '(not given)'}",
        f"CUSTOM URL: {url or '(not given)'}",
        f"RECOMMENDATIONS RECEIVED: {recs if recs is not None else 'unknown'}",
        f"BANNER: {'custom banner' if data.get('has_banner') else 'default or unknown'}",
        f"PHOTO: {'professional headshot' if data.get('has_photo') else 'unknown or not professional'}",
    ]
    user = (
        "Review this LinkedIn profile against the profile playbooks and score all 9 parts.\n\n"
        + llm.untrusted("\n\n".join(fields), "linkedin_profile")
        + "\n\nRules:\n"
        "- Score every part 0-10. A part that wasn't given scores 0-3, and its fix says what to add.\n"
        "- Rewrites keep the author's real facts. Never invent clients, numbers or titles; use [placeholders] "
        "where a fact would help.\n"
        "- Headlines follow the headline formula and stay under 220 characters."
    )
    review = llm.complete_json("profile_review", user, ProfileReview, packs=("profile",), effort="medium",
                               max_tokens=10000)

    by_part = {p.part: p for p in review.parts}
    parts = []
    for pid, label in PARTS:
        p = by_part.get(pid)
        parts.append({"part": pid, "label": label,
                      "score": max(0, min(10, p.score)) if p else None,
                      "verdict": p.verdict.strip() if p else "Not reviewed",
                      "fix": p.fix.strip() if p else ""})
    part = {x["part"]: x for x in parts}
    checked = _url_check(url)
    if checked:
        part["custom_url"]["score"], part["custom_url"]["verdict"], part["custom_url"]["fix"] = checked
    if len(headline) > HEADLINE_MAX:
        h = part["headline"]
        h["score"] = min(h["score"] if h["score"] is not None else 5, 5)
        h["verdict"] = f"It's {len(headline)} characters; LinkedIn cuts headlines at {HEADLINE_MAX}. " + h["verdict"]

    scored = [x["score"] for x in parts if x["score"] is not None]
    return {
        "overall": round(100 * sum(scored) / (10 * len(scored))) if scored else 0,
        "parts": parts,
        "headline_options": [h.strip() for h in review.headline_options
                             if h.strip() and len(h.strip()) <= HEADLINE_MAX][:3],
        "about_rewrite": review.about_rewrite.strip()[:ABOUT_MAX],
        "experience_bullets": [b.strip() for b in review.experience_bullets if b.strip()][:5],
        "top_priority": review.top_priority.strip(),
    }
