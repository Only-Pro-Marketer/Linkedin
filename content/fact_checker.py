"""Fact-check generated LinkedIn posts before they reach the queue.

Uses Claude (structured output) to flag invented or misleading claims and
anything off-brand, judged against the brand profile in the system prompt.
The verdict is advisory: it is shown on the post card, it does not block.
"""

import logging
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

import llm
from config import settings

logger = logging.getLogger(__name__)

FACT_CHECK_RULES = """You are a strict but fair fact-checker for LinkedIn posts written for the person in <brand_voice>.

Flag anything that is:
- factual: a statistic, amount or claim presented as real fact that is made up or unverifiable
- misleading: exaggerated, cherry-picked, or likely to be misread
- brand: contradicts the author's identity, business or audience in the brand profile
- persona: first-person experience the brand profile does not support (invented clients, results, credentials), or reads like generic AI
- outdated: references old data, discontinued platforms or changed norms

Do NOT flag: clearly hypothetical examples ("imagine spending $5K"), widely cited industry benchmarks, or general marketing wisdom.

Verdict: "pass" = safe to publish; "warning" = worth a look; "fail" = serious problem that must be fixed."""


class FactIssue(BaseModel):
    type: Literal["factual", "misleading", "brand", "persona", "outdated"]
    claim: str
    problem: str
    suggestion: str


class FactCheckResult(BaseModel):
    verdict: Literal["pass", "warning", "fail"]
    issues: list[FactIssue]
    summary: str


def _result(verdict: str, summary: str, issues=None) -> dict:
    return {"verdict": verdict, "issues": issues or [], "summary": summary,
            "checked_at": datetime.utcnow().isoformat()}


class FactChecker:
    """Checks posts for factual accuracy and brand consistency."""

    def check(self, post_content: str, topic: str = "", research_context: str = "") -> dict:
        """Return {verdict, issues, summary, checked_at}. Never raises."""
        if not settings.FACT_CHECK_ENABLED:
            return _result("pass", "Fact-checking is turned off.")

        user = f"""Fact-check this LinkedIn post.

POST:
---
{post_content}
---

TOPIC: {topic or "not specified"}
{("SOURCE MATERIAL USED TO WRITE IT:" + chr(10) + llm.untrusted(research_context, "research")) if research_context else ""}"""
        try:
            result = llm.complete_json("fact_check", user, FactCheckResult, instructions=FACT_CHECK_RULES)
        except llm.LLMError as e:
            logger.warning("Fact-check unavailable: %s", e)
            return _result("warning", f"Fact-check unavailable: {e}")

        logger.info("Fact-check: %s (%d issues)", result.verdict, len(result.issues))
        return _result(result.verdict, result.summary, [i.model_dump() for i in result.issues])
