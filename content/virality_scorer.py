"""Predict a post's reach potential with Claude (structured output) + heuristics.

This is a secondary "predicted reach" number. The deterministic quality
check (content/humanizer.py) decides whether a post is ready to publish.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

import llm

logger = logging.getLogger(__name__)

SCORING_RULES = """You are a LinkedIn content strategist predicting a post's reach potential for the author in <brand_voice>.

Score each dimension (use the full range; be honest, most posts are average):
- hook_power 0-25: does line 1 stop the scroll? Statements and specific numbers beat questions.
- structure 0-20: whitespace, short paragraphs, easy to scan, no walls of text.
- value_insight 0-20: specific, non-obvious, useful; concrete numbers with context.
- engagement_trigger 0-15: a specific closing question people can answer from experience.
- authenticity 0-10: sounds like this person, not generic AI (no filler vocabulary, no staccato, no fake candor).
- relevance 0-10: timely or evergreen-valuable for this author's audience.
total_score is the sum (0-100)."""


class ViralityScore(BaseModel):
    total_score: int
    hook_power: int
    structure: int
    value_insight: int
    engagement_trigger: int
    authenticity: int
    relevance: int
    strengths: list[str]
    improvements: list[str]
    one_line_verdict: str


CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "database" / "scorer_calibration.json"

LIMITS = {"hook_power": 25, "structure": 20, "value_insight": 20, "engagement_trigger": 15,
          "authenticity": 10, "relevance": 10}


def tier(score: int) -> str:
    if score >= 85:
        return "viral"
    if score >= 65:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


class ViralityScorer:
    """Scores LinkedIn posts for predicted reach potential."""

    def __init__(self):
        self._calibration_offset = self._load_calibration_offset()

    def _load_calibration_offset(self) -> int:
        if CALIBRATION_PATH.exists():
            try:
                return int(json.loads(CALIBRATION_PATH.read_text()).get("offset", 0))
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
        return 0

    @staticmethod
    def save_calibration_offset(offset: int) -> None:
        """Save calibration offset (capped at ±10)."""
        offset = max(-10, min(10, offset))
        CALIBRATION_PATH.write_text(json.dumps({"offset": offset, "updated_at": datetime.now().isoformat()}))
        logger.info("Saved virality scorer calibration offset: %d", offset)

    def score(self, post_content: str, topic: str = "") -> dict:
        """Return the score dict (total_score, dimensions, tier, notes). Never raises."""
        user = f"Score this LinkedIn post.\n\nPOST:\n---\n{post_content}\n---\n\nTOPIC: {topic or 'not specified'}"
        try:
            s = llm.complete_json("virality_score", user, ViralityScore, instructions=SCORING_RULES)
        except llm.LLMError as e:
            logger.warning("Virality scoring unavailable: %s", e)
            return self.score_from_heuristics(post_content)
        return self.finalize(s.model_dump(), post_content)

    def finalize(self, dims: dict, post_content: str) -> dict:
        """Clamp model dimensions, add heuristics + calibration, compute the tier."""
        heuristic = self._heuristic_check(post_content)
        result = dict(dims)
        for key, cap in LIMITS.items():
            result[key] = max(0, min(cap, int(result.get(key, 0) or 0)))
        base = sum(result[k] for k in LIMITS)
        total = max(1, min(100, base + heuristic["adjustment"] - self._calibration_offset))
        result.update(total_score=total, predicted_performance=tier(total), heuristic_notes=heuristic["notes"])
        result.setdefault("strengths", [])
        result.setdefault("improvements", [])
        result.setdefault("one_line_verdict", "")
        return result

    def score_from_heuristics(self, post_content: str) -> dict:
        return self._fallback_score(self._heuristic_check(post_content))

    def _heuristic_check(self, content: str) -> dict:
        """Structural signals backed by the 2026 reach data."""
        notes, adjustment = [], 0
        lines = [l for l in content.strip().split("\n")]
        words = content.split()
        first = next((l.strip() for l in lines if l.strip()), "")

        if first.endswith("?"):
            adjustment -= 4
            notes.append("Opens with a question (question hooks underperform)")
        if re.search(r"\d", first):
            adjustment += 3
            notes.append("Number in the first line")
        if len(first) > 200:
            adjustment -= 5
            notes.append("Hook too long")
        elif len(first) <= 100:
            adjustment += 1

        if 120 <= len(words) <= 260:
            adjustment += 3
            notes.append("Length in the sweet spot")
        elif len(words) > 350:
            adjustment -= 5
            notes.append("Too long")
        elif len(words) < 50:
            adjustment -= 3
            notes.append("Too short")

        if sum(1 for l in lines if not l.strip()) >= 3:
            adjustment += 2
            notes.append("Good whitespace")

        if not re.search(r"\$[\d,.]+|\d+(?:\.\d+)?%|\d+x\b|\b\d{2,}\b", content):
            adjustment -= 3
            notes.append("No specific numbers")

        last = next((l.strip() for l in reversed(lines) if l.strip()), "")
        if last.endswith("?") and not re.fullmatch(r"(thoughts|agree|what do you think)\??", last.lower()):
            adjustment += 2
            notes.append("Ends with a specific question")

        return {"adjustment": adjustment, "notes": notes}

    def _fallback_score(self, heuristic: dict) -> dict:
        total = max(1, min(100, 50 + heuristic["adjustment"]))
        return {
            "total_score": total, **{k: 0 for k in LIMITS},
            "strengths": [], "improvements": [],
            "predicted_performance": tier(total),
            "one_line_verdict": "Estimated from structure only (AI scoring unavailable).",
            "heuristic_notes": heuristic["notes"],
        }
