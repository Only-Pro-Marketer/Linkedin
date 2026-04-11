"""Fact-check generated LinkedIn posts before queuing.

Uses Claude to verify claims, statistics, brand consistency,
and persona accuracy against soul.md and web search.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import anthropic

from config import settings, get_anthropic_client

logger = logging.getLogger(__name__)

# Load soul.md once at module level
SOUL_PATH = Path(__file__).resolve().parent.parent / "soul" / "soul.md"
_soul_content = ""
if SOUL_PATH.exists():
    _soul_content = SOUL_PATH.read_text()


FACT_CHECK_PROMPT = """You are a rigorous fact-checker for LinkedIn posts.

Your job is to review a LinkedIn post and flag anything that is:
1. **Factually false or unverifiable** — statistics, percentages, dollar amounts, or claims presented as facts that are made up or cannot be confirmed
2. **Misleading** — cherry-picked data, exaggerated claims, or statements that could be misinterpreted
3. **Brand inconsistent** — anything that contradicts the author's identity as described in their brand profile below
4. **Persona violations** — speaking from a perspective that doesn't match the brand profile, using corporate jargon, sounding like generic AI
5. **Outdated information** — referencing old data, discontinued platforms, or changed industry norms

IMPORTANT DISTINCTIONS:
- Numbers used in HYPOTHETICAL SCENARIOS or ILLUSTRATIVE EXAMPLES are OK (e.g., "imagine spending $5K on ads" or "if your store does $50K/month"). These don't need to be verified.
- Numbers presented as REAL FACTS or PERSONAL EXPERIENCE need scrutiny (e.g., "I generated $500K for a client" or "studies show 73% of consumers prefer...").
- Well-known industry benchmarks are OK (e.g., "email marketing has 36x ROI" — this is widely cited).
- General marketing wisdom is OK (e.g., "most brands don't email enough").

BRAND REFERENCE (soul.md):
---
{soul_content}
---

POST TO FACT-CHECK:
---
{post_content}
---

TOPIC/CONTEXT: {topic}

RESEARCH CONTEXT USED TO GENERATE THIS POST:
{research_context}

Respond in this exact JSON format:
{{
  "verdict": "pass" | "fail" | "warning",
  "issues": [
    {{
      "type": "factual" | "misleading" | "brand" | "persona" | "outdated",
      "claim": "the specific claim from the post",
      "problem": "why this is an issue",
      "suggestion": "how to fix it"
    }}
  ],
  "summary": "1-2 sentence overall assessment"
}}

Rules for verdict:
- "pass" = no issues found, post is safe to publish
- "warning" = minor issues that the user should review but post could still go out
- "fail" = serious factual errors, brand violations, or misleading claims that MUST be fixed

Be strict but fair. Don't flag hypothetical examples or common marketing wisdom.
Only output the JSON, nothing else."""


class FactChecker:
    """Checks generated LinkedIn posts for factual accuracy and brand consistency."""

    def __init__(self):
        self.client = get_anthropic_client()
        self.soul_content = _soul_content

    def check(
        self,
        post_content: str,
        topic: str = "",
        research_context: str = "",
    ) -> dict:
        """Fact-check a post and return verdict + issues.

        Returns dict with:
            - verdict: "pass", "fail", or "warning"
            - issues: list of issue dicts
            - summary: brief assessment
            - checked_at: ISO timestamp
        """
        if not settings.FACT_CHECK_ENABLED:
            return {
                "verdict": "pass",
                "issues": [],
                "summary": "Fact-checking disabled.",
                "checked_at": datetime.utcnow().isoformat(),
            }

        prompt = FACT_CHECK_PROMPT.format(
            soul_content=self.soul_content,
            post_content=post_content,
            topic=topic or "not specified",
            research_context=research_context or "none provided",
        )

        try:
            message = self.client.messages.create(
                model=settings.FACT_CHECK_MODEL,
                max_tokens=1000,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()

            # Parse JSON from response (handle markdown code blocks)
            json_text = raw
            if "```" in raw:
                json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
                if json_match:
                    json_text = json_match.group(1).strip()

            result = json.loads(json_text)

            # Validate structure
            verdict = result.get("verdict", "warning")
            if verdict not in ("pass", "fail", "warning"):
                verdict = "warning"

            checked = {
                "verdict": verdict,
                "issues": result.get("issues", []),
                "summary": result.get("summary", ""),
                "checked_at": datetime.utcnow().isoformat(),
            }

            issue_count = len(checked["issues"])
            logger.info(
                "Fact-check result: verdict=%s, issues=%d — %s",
                checked["verdict"],
                issue_count,
                checked["summary"],
            )
            return checked

        except json.JSONDecodeError as e:
            logger.error("Failed to parse fact-check response: %s", e)
            return {
                "verdict": "warning",
                "issues": [
                    {
                        "type": "factual",
                        "claim": "N/A",
                        "problem": f"Fact-check response could not be parsed: {e}",
                        "suggestion": "Review post manually.",
                    }
                ],
                "summary": "Fact-check parsing failed — manual review recommended.",
                "checked_at": datetime.utcnow().isoformat(),
            }
        except anthropic.APIError as e:
            logger.error("Claude API error during fact-check: %s", e)
            return {
                "verdict": "warning",
                "issues": [],
                "summary": f"Fact-check API call failed: {e}",
                "checked_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error("Unexpected fact-check error: %s", e)
            return {
                "verdict": "warning",
                "issues": [],
                "summary": f"Fact-check error: {e}",
                "checked_at": datetime.utcnow().isoformat(),
            }
