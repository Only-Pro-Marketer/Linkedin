"""Build dynamic performance context for prompt injection.

Queries accumulated learning insights and builds a PERFORMANCE CONTEXT block
that gets injected into Claude prompts, so every new post benefits from past
performance data, rejection feedback, and edit patterns.
"""

import json
import logging
import time as _time
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from database.models import (
    AnalysisRun,
    InsightCategory,
    LearningInsight,
    PostPerformance,
    PostStatus,
    QueuedPost,
)

logger = logging.getLogger(__name__)


class LearningContext:
    """Queries learning insights and builds prompt context."""

    # Class-level cache: shared across instances within the same process
    _cache: dict = {}
    _CACHE_TTL = 300  # 5 minutes

    def __init__(self, db: Session):
        self.db = db

    def build_performance_context(self, max_insights: int | None = None) -> str:
        """Build the PERFORMANCE CONTEXT section for prompt injection.

        Returns a formatted string ready to inject between VIRALITY_RULES and TEMPLATE.
        Returns empty string when no insights exist (cold start).
        Uses a 5-minute TTL cache to avoid repeated DB queries during batch generation.
        """
        if max_insights is None:
            max_insights = settings.LEARNING_MAX_PROMPT_INSIGHTS

        cache_key = f"perf_context_{max_insights}"
        now = _time.time()
        if cache_key in self._cache:
            cached_result, cached_at = self._cache[cache_key]
            if now - cached_at < self._CACHE_TTL:
                return cached_result

        insights = self._get_active_insights(max_insights)
        top_traits = self._get_top_performing_characteristics(n=3)
        avoidance = self._get_rejection_avoidance_directives()

        # If nothing to inject, return empty
        if not insights and not top_traits and not avoidance:
            return ""

        sections = []
        sections.append("PERFORMANCE CONTEXT (data from your actual LinkedIn posts):")
        sections.append("")

        if top_traits:
            sections.append("YOUR BEST PERFORMING POSTS share these traits:")
            for trait in top_traits:
                sections.append(f"- {trait}")
            sections.append("")

        if avoidance:
            sections.append("AVOID these patterns (previously rejected):")
            for a in avoidance:
                sections.append(f"- {a}")
            sections.append("")

        directives = [i.prompt_directive for i in insights if i.prompt_directive]
        if directives:
            sections.append("DATA-DRIVEN GUIDELINES:")
            for d in directives:
                sections.append(f"- {d}")

        context = "\n".join(sections)

        # Track usage
        for i in insights:
            i.times_used_in_prompts = (i.times_used_in_prompts or 0) + 1
        self.db.commit()

        logger.info(
            "Injected performance context: %d insights, %d top traits, %d avoidances",
            len(insights),
            len(top_traits),
            len(avoidance),
        )
        self._cache[cache_key] = (context, _time.time())
        return context

    def _get_active_insights(self, limit: int) -> list[LearningInsight]:
        """Get active insights ordered by confidence and recency."""
        min_confidence = settings.LEARNING_MIN_CONFIDENCE
        return (
            self.db.query(LearningInsight)
            .filter(
                LearningInsight.is_active == True,
                LearningInsight.confidence >= min_confidence,
            )
            .order_by(
                LearningInsight.confidence.desc(),
                LearningInsight.created_at.desc(),
            )
            .limit(limit)
            .all()
        )

    def _get_top_performing_characteristics(self, n: int = 3) -> list[str]:
        """Extract characteristics of the top N performing posts."""
        top_posts = (
            self.db.query(QueuedPost, PostPerformance)
            .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
            .filter(QueuedPost.status == PostStatus.POSTED)
            .order_by(
                (
                    PostPerformance.likes
                    + PostPerformance.comments * 3
                    + PostPerformance.shares * 5
                ).desc()
            )
            .limit(n)
            .all()
        )

        if not top_posts:
            return []

        traits = []
        for post, perf in top_posts:
            score = (perf.likes or 0) + (perf.comments or 0) * 3 + (perf.shares or 0) * 5
            parts = []
            if post.hook_type:
                parts.append(f"{post.hook_type} hook")
            if post.template_name:
                parts.append(f"{post.template_name} template")
            if post.word_count:
                parts.append(f"{post.word_count} words")
            trait = ", ".join(parts) if parts else "unknown structure"
            traits.append(f"{trait} (engagement score: {score})")

        return traits

    def _get_rejection_avoidance_directives(self) -> list[str]:
        """Build avoidance directives from recent rejections."""
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        rejected = (
            self.db.query(QueuedPost)
            .filter(
                QueuedPost.status == PostStatus.REJECTED,
                QueuedPost.updated_at >= thirty_days_ago,
            )
            .all()
        )

        if not rejected:
            return []

        # Count structured rejection categories
        category_counts: dict[str, int] = {}
        for post in rejected:
            if post.rejection_categories:
                try:
                    cats = json.loads(post.rejection_categories)
                    for cat in cats:
                        category_counts[cat] = category_counts.get(cat, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    pass

        # Also scan free-text reasons for common patterns
        reason_keywords = {
            "generic": "too_generic",
            "long": "too_long",
            "short": "too_short",
            "hook": "hook_too_weak",
            "ai": "sounds_ai",
            "tone": "wrong_tone",
            "brand": "off_brand",
            "actionable": "not_actionable",
        }
        for post in rejected:
            if post.rejection_reason and not post.rejection_categories:
                reason_lower = post.rejection_reason.lower()
                for keyword, cat in reason_keywords.items():
                    if keyword in reason_lower:
                        category_counts[cat] = category_counts.get(cat, 0) + 1

        if not category_counts:
            return []

        # Build human-readable avoidance directives for top categories
        labels = {
            "hook_too_weak": "Weak hooks",
            "off_brand": "Off-brand content",
            "too_generic": "Generic advice without specific numbers",
            "too_long": "Posts that are too long",
            "too_short": "Posts that are too short",
            "not_actionable": "Content without actionable takeaways",
            "wrong_tone": "Wrong tone for the topic",
            "wrong_topic": "Off-topic content",
            "factually_wrong": "Factually inaccurate claims",
            "sounds_ai": "Content that sounds AI-generated",
        }

        directives = []
        for cat, count in sorted(category_counts.items(), key=lambda x: -x[1])[:3]:
            label = labels.get(cat, cat.replace("_", " ").title())
            directives.append(f"{label} (rejected {count}x in last 30 days)")

        return directives
