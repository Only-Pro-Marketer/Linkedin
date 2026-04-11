"""Score LinkedIn posts for predicted virality using Claude + heuristics."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

import anthropic

from config import settings, get_anthropic_client

logger = logging.getLogger(__name__)

# Load soul.md for brand-aware scoring
SOUL_PATH = Path(__file__).resolve().parent.parent / "soul" / "soul.md"
_soul_content = ""
if SOUL_PATH.exists():
    _soul_content = SOUL_PATH.read_text()


VIRALITY_SCORE_PROMPT = """You are a LinkedIn content strategist analyzing a post for viral potential.

Score this LinkedIn post on a 1-100 scale across these dimensions:

1. **Hook Power** (0-25): How scroll-stopping is the first line? Does it create curiosity, surprise, or urgency?
2. **Structure & Readability** (0-20): Whitespace, short paragraphs, one thought per line, easy to scan.
3. **Value & Insight** (0-20): Does it give actionable, specific, non-obvious insights? Concrete numbers?
4. **Engagement Trigger** (0-15): Does it end with a question, CTA, or reason to comment? Will people want to share their opinion?
5. **Authenticity & Voice** (0-10): Does it feel human, personal, and relatable — or generic and AI-sounding?
6. **Relevance & Timing** (0-10): Is the topic currently trending or evergreen-valuable for e-commerce professionals?

BRAND CONTEXT (from soul.md):
{soul_context}

POST TO SCORE:
---
{post_content}
---

TOPIC: {topic}

Respond in this exact JSON format:
{{
  "total_score": <number 1-100>,
  "hook_power": <number 0-25>,
  "structure": <number 0-20>,
  "value_insight": <number 0-20>,
  "engagement_trigger": <number 0-15>,
  "authenticity": <number 0-10>,
  "relevance": <number 0-10>,
  "strengths": ["strength 1", "strength 2"],
  "improvements": ["improvement 1", "improvement 2"],
  "predicted_performance": "low" | "medium" | "high" | "viral",
  "one_line_verdict": "Brief 1-sentence assessment"
}}

Rules for predicted_performance:
- "low" = score < 40
- "medium" = score 40-64
- "high" = score 65-84
- "viral" = score 85+

Only output the JSON, nothing else."""


CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "database" / "scorer_calibration.json"


class ViralityScorer:
    """Scores LinkedIn posts for predicted viral potential."""

    def __init__(self):
        self.client = get_anthropic_client()
        self._calibration_offset = self._load_calibration_offset()

    def _load_calibration_offset(self) -> int:
        """Load the calibration offset from file. Returns 0 if not set."""
        if CALIBRATION_PATH.exists():
            try:
                data = json.loads(CALIBRATION_PATH.read_text())
                return data.get("offset", 0)
            except (json.JSONDecodeError, KeyError):
                pass
        return 0

    @staticmethod
    def save_calibration_offset(offset: int) -> None:
        """Save calibration offset to file (capped at +/-10)."""
        offset = max(-10, min(10, offset))
        CALIBRATION_PATH.write_text(json.dumps({
            "offset": offset,
            "updated_at": datetime.now().isoformat(),
        }))
        logger.info("Saved virality scorer calibration offset: %d", offset)

    def score(self, post_content: str, topic: str = "") -> dict:
        """Score a post for virality and return detailed breakdown.

        Returns dict with:
            - total_score: 1-100
            - breakdown: hook_power, structure, value_insight, etc.
            - predicted_performance: low/medium/high/viral
            - strengths, improvements, one_line_verdict
        """
        # Quick heuristic pre-check
        heuristic = self._heuristic_check(post_content)

        # Claude scoring
        # Build soul context summary (first 500 chars) for scoring
        soul_ctx = _soul_content[:500] if _soul_content else "No brand profile configured"
        prompt = VIRALITY_SCORE_PROMPT.format(
            post_content=post_content,
            topic=topic or "not specified",
            soul_context=soul_ctx,
        )

        try:
            message = self.client.messages.create(
                model=settings.FACT_CHECK_MODEL,
                max_tokens=800,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()

            # Parse JSON
            json_text = raw
            if "```" in raw:
                json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
                if json_match:
                    json_text = json_match.group(1).strip()

            result = json.loads(json_text)

            # Merge heuristic adjustments and calibration offset
            total = result.get("total_score", 50)
            total = max(1, min(100, total + heuristic["adjustment"] - self._calibration_offset))
            result["total_score"] = total
            result["heuristic_notes"] = heuristic["notes"]

            # Recalculate performance tier
            if total >= 85:
                result["predicted_performance"] = "viral"
            elif total >= 65:
                result["predicted_performance"] = "high"
            elif total >= 40:
                result["predicted_performance"] = "medium"
            else:
                result["predicted_performance"] = "low"

            logger.info(
                "Virality score: %d/100 (%s) — %s",
                total,
                result["predicted_performance"],
                result.get("one_line_verdict", ""),
            )
            return result

        except json.JSONDecodeError as e:
            logger.error("Failed to parse virality score response: %s", e)
            return self._fallback_score(post_content, heuristic)
        except anthropic.APIError as e:
            logger.error("Claude API error during virality scoring: %s", e)
            return self._fallback_score(post_content, heuristic)
        except Exception as e:
            logger.error("Unexpected virality scoring error: %s", e)
            return self._fallback_score(post_content, heuristic)

    def _heuristic_check(self, content: str) -> dict:
        """Quick structural heuristics for bonus/penalty adjustments."""
        notes = []
        adjustment = 0
        lines = content.strip().split("\n")
        words = content.split()
        word_count = len(words)

        # Hook length (first line)
        if lines:
            first_line = lines[0].strip()
            if len(first_line) <= 80:
                adjustment += 3
                notes.append("Short punchy hook")
            elif len(first_line) > 200:
                adjustment -= 5
                notes.append("Hook too long")

        # Word count sweet spot
        if 100 <= word_count <= 250:
            adjustment += 3
            notes.append("Word count in sweet spot")
        elif word_count > 350:
            adjustment -= 5
            notes.append("Post too long for LinkedIn")
        elif word_count < 50:
            adjustment -= 3
            notes.append("Post too short")

        # Whitespace / readability
        blank_lines = sum(1 for l in lines if l.strip() == "")
        if blank_lines >= 3:
            adjustment += 2
            notes.append("Good whitespace")

        # Personal pronoun in first line (personal/BTS content gets 10x engagement)
        if lines:
            first_lower = lines[0].strip().lower()
            if any(first_lower.startswith(p) for p in ["i ", "i'", "my ", "we ", "our "]):
                adjustment += 2
                notes.append("Personal hook (high engagement pattern)")

        # Numbers / specificity
        numbers = re.findall(r"\$[\d,]+|\d+%|\d+x|\d+K", content)
        if len(numbers) >= 2:
            adjustment += 3
            notes.append("Contains specific numbers")
        elif len(numbers) == 0:
            adjustment -= 3
            notes.append("No specific numbers or dollar amounts")

        # Question at end (easy-to-answer questions get 72% more comments)
        last_content_line = ""
        for l in reversed(lines):
            stripped = l.strip()
            if stripped:
                last_content_line = stripped
                break
        if "?" in last_content_line:
            adjustment += 2
            notes.append("Ends with question (72% more comments)")

        return {"adjustment": adjustment, "notes": notes}

    def _fallback_score(self, content: str, heuristic: dict) -> dict:
        """Fallback scoring using heuristics only when Claude fails."""
        base_score = 50 + heuristic["adjustment"]
        base_score = max(1, min(100, base_score))

        if base_score >= 85:
            perf = "viral"
        elif base_score >= 65:
            perf = "high"
        elif base_score >= 40:
            perf = "medium"
        else:
            perf = "low"

        return {
            "total_score": base_score,
            "hook_power": 0,
            "structure": 0,
            "value_insight": 0,
            "engagement_trigger": 0,
            "authenticity": 0,
            "relevance": 0,
            "strengths": [],
            "improvements": [],
            "predicted_performance": perf,
            "one_line_verdict": "Scored using heuristics only (Claude unavailable).",
            "heuristic_notes": heuristic["notes"],
        }
