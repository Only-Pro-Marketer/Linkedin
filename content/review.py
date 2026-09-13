"""One AI call that fact-checks AND scores a post (saves a call per post).

Returns the same dict shapes FactChecker.check() and ViralityScorer.score()
produce, so the stored JSON and the UI stay unchanged.
"""

import logging
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

import llm
from config import settings
from content.fact_checker import FACT_CHECK_RULES, FactIssue
from content.virality_scorer import SCORING_RULES, ViralityScorer

logger = logging.getLogger(__name__)


class PostReview(BaseModel):
    fact_verdict: Literal["pass", "warning", "fail"]
    fact_issues: list[FactIssue]
    fact_summary: str
    hook_power: int
    structure: int
    value_insight: int
    engagement_trigger: int
    authenticity: int
    relevance: int
    strengths: list[str]
    improvements: list[str]
    one_line_verdict: str


REVIEW_RULES = f"""Review a LinkedIn post in two parts.

PART 1 — FACT CHECK
{FACT_CHECK_RULES}

PART 2 — REACH SCORE
{SCORING_RULES}"""


def review_post(content: str, topic: str = "", research_context: str = "") -> tuple[dict, dict]:
    """Return (fact_check_dict, virality_dict). Never raises."""
    scorer = ViralityScorer()
    now = datetime.utcnow().isoformat()
    source = f"\nSOURCE MATERIAL USED TO WRITE IT:\n{llm.untrusted(research_context, 'research')}" if research_context else ""
    user = f"Review this LinkedIn post.\n\nPOST:\n---\n{content}\n---\n\nTOPIC: {topic or 'not specified'}{source}"
    try:
        r = llm.complete_json("post_review", user, PostReview, instructions=REVIEW_RULES)
    except llm.LLMError as e:
        logger.warning("Post review unavailable: %s", e)
        fact = {"verdict": "warning", "issues": [], "summary": f"Fact-check unavailable: {e}", "checked_at": now}
        return fact, scorer.score_from_heuristics(content)

    if settings.FACT_CHECK_ENABLED:
        fact = {"verdict": r.fact_verdict, "issues": [i.model_dump() for i in r.fact_issues],
                "summary": r.fact_summary, "checked_at": now}
    else:
        fact = {"verdict": "pass", "issues": [], "summary": "Fact-checking is turned off.", "checked_at": now}
    dims = r.model_dump(exclude={"fact_verdict", "fact_issues", "fact_summary"})
    return fact, scorer.finalize(dims, content)
