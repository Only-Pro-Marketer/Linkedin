"""Analyze post performance patterns and generate learning insights.

Inspired by Karpathy's autoresearch: periodically analyze all posted content,
extract what works vs. what doesn't, and store actionable insights that get
injected into future generation prompts.
"""

import json
import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from database.models import (
    AnalysisRun,
    InsightCategory,
    InsightSource,
    LearningInsight,
    PostPerformance,
    PostStatus,
    QueuedPost,
)

logger = logging.getLogger(__name__)


def _engagement_score(perf: PostPerformance) -> float:
    """Consistent engagement scoring: likes + comments*3 + shares*5."""
    return (perf.likes or 0) + (perf.comments or 0) * 3 + (perf.shares or 0) * 5


def _confidence_from_sample(n: int, effect_size: float = 0.0) -> float:
    """Calculate confidence score from sample size and effect magnitude.

    n < 5  -> 0.3
    n 5-15 -> 0.5
    n 15-30 -> 0.7
    n > 30 -> 0.9
    Bonus +0.05 if effect_size > 0.5 (large effect).
    """
    if n < 5:
        base = 0.3
    elif n < 15:
        base = 0.5
    elif n < 30:
        base = 0.7
    else:
        base = 0.9
    if effect_size > 0.5:
        base = min(base + 0.05, 1.0)
    return round(base, 2)


class PatternAnalyzer:
    """Extracts performance patterns from posted content and generates LearningInsight records."""

    def __init__(self, db: Session):
        self.db = db
        self._cached_posted_rows = None

    def run_full_analysis(self) -> dict:
        """Run all analysis types and return summary."""
        self._cached_posted_rows = None  # Reset cache for fresh data
        start = time.time()

        # Check minimum post threshold
        posted_count = (
            self.db.query(func.count(QueuedPost.id))
            .filter(QueuedPost.status == PostStatus.POSTED)
            .scalar()
        )
        if posted_count < settings.LEARNING_MIN_POSTS_FOR_ANALYSIS:
            logger.info(
                "Only %d posted posts (need %d) — skipping analysis",
                posted_count,
                settings.LEARNING_MIN_POSTS_FOR_ANALYSIS,
            )
            return {"skipped": True, "reason": "insufficient_data", "posted_count": posted_count}

        results = {}
        total_created = 0
        total_updated = 0
        total_superseded = 0

        for name, method in [
            ("hook", self.analyze_hook_performance),
            ("tone", self.analyze_tone_performance),
            ("template", self.analyze_template_performance),
            ("topic", self.analyze_topic_performance),
            ("length", self.analyze_length_performance),
            ("timing", self.analyze_timing_performance),
            ("time_of_day", self.analyze_time_of_day_performance),
            ("media_type", self.analyze_media_type_performance),
            ("rejection", self.analyze_rejection_patterns),
            ("edit", self.analyze_edit_patterns),
            ("research", self.analyze_research_performance),
            ("prediction_accuracy", self.analyze_prediction_accuracy),
        ]:
            try:
                created, updated, superseded = method()
                results[name] = {"created": created, "updated": updated, "superseded": superseded}
                total_created += created
                total_updated += updated
                total_superseded += superseded
            except Exception as e:
                logger.error("Analysis '%s' failed: %s", name, e)
                results[name] = {"error": str(e)}

        duration = round(time.time() - start, 2)

        # Record the analysis run
        run = AnalysisRun(
            run_type="full",
            posts_analyzed=posted_count,
            insights_created=total_created,
            insights_updated=total_updated,
            insights_superseded=total_superseded,
            run_duration_seconds=duration,
        )
        self.db.add(run)
        self.db.commit()

        logger.info(
            "Full analysis complete: %d posts, %d created, %d updated, %d superseded in %.1fs",
            posted_count,
            total_created,
            total_updated,
            total_superseded,
            duration,
        )
        return results

    # ------------------------------------------------------------------
    # Individual analysis methods — each returns (created, updated, superseded)
    # ------------------------------------------------------------------

    def analyze_hook_performance(self) -> tuple[int, int, int]:
        """Compare engagement by hook_type across all posted posts."""
        rows = self._get_posted_with_performance()
        if not rows:
            return (0, 0, 0)

        # Group by hook_type
        by_hook: dict[str, list[float]] = defaultdict(list)
        for post, perf in rows:
            if post.hook_type:
                by_hook[post.hook_type].append(_engagement_score(perf))

        if len(by_hook) < 2:
            return (0, 0, 0)

        overall_avg = sum(s for scores in by_hook.values() for s in scores) / max(
            sum(len(s) for s in by_hook.values()), 1
        )

        created, updated, superseded = 0, 0, 0
        for hook_type, scores in by_hook.items():
            avg = sum(scores) / len(scores)
            n = len(scores)
            if n < 3:
                continue

            ratio = avg / overall_avg if overall_avg > 0 else 1.0
            effect_size = abs(ratio - 1.0)

            if ratio >= 1.2:
                pct = round((ratio - 1.0) * 100)
                c, u, s = self._create_or_update_insight(
                    category=InsightCategory.HOOK_STYLE,
                    source=InsightSource.PERFORMANCE_ANALYSIS,
                    insight_text=f"{hook_type} hooks outperform average by {pct}% (avg {avg:.0f} vs {overall_avg:.0f})",
                    prompt_directive=f"Prefer {hook_type}-style hooks — they get {pct}% more engagement than other styles.",
                    confidence=_confidence_from_sample(n, effect_size),
                    sample_size=n,
                    evidence={"hook_type": hook_type, "avg_score": round(avg, 1), "overall_avg": round(overall_avg, 1), "ratio": round(ratio, 2)},
                )
                created += c
                updated += u
                superseded += s
            elif ratio <= 0.7:
                pct = round((1.0 - ratio) * 100)
                c, u, s = self._create_or_update_insight(
                    category=InsightCategory.HOOK_STYLE,
                    source=InsightSource.PERFORMANCE_ANALYSIS,
                    insight_text=f"{hook_type} hooks underperform average by {pct}%",
                    prompt_directive=f"Avoid {hook_type}-style hooks — they get {pct}% less engagement.",
                    confidence=_confidence_from_sample(n, effect_size),
                    sample_size=n,
                    evidence={"hook_type": hook_type, "avg_score": round(avg, 1), "overall_avg": round(overall_avg, 1), "ratio": round(ratio, 2)},
                )
                created += c
                updated += u
                superseded += s

        return (created, updated, superseded)

    def analyze_tone_performance(self) -> tuple[int, int, int]:
        """Compare engagement by tone extracted from generation_prompt."""
        rows = self._get_posted_with_performance()
        if not rows:
            return (0, 0, 0)

        by_tone: dict[str, list[float]] = defaultdict(list)
        for post, perf in rows:
            tone = self._extract_tone(post.generation_prompt)
            if tone:
                by_tone[tone].append(_engagement_score(perf))

        if len(by_tone) < 2:
            return (0, 0, 0)

        overall_avg = sum(s for scores in by_tone.values() for s in scores) / max(
            sum(len(s) for s in by_tone.values()), 1
        )

        created, updated, superseded = 0, 0, 0
        for tone, scores in by_tone.items():
            avg = sum(scores) / len(scores)
            n = len(scores)
            if n < 3:
                continue

            ratio = avg / overall_avg if overall_avg > 0 else 1.0
            effect_size = abs(ratio - 1.0)

            if ratio >= 1.2:
                pct = round((ratio - 1.0) * 100)
                c, u, s = self._create_or_update_insight(
                    category=InsightCategory.TONE,
                    source=InsightSource.PERFORMANCE_ANALYSIS,
                    insight_text=f"'{tone}' tone outperforms average by {pct}%",
                    prompt_directive=f"The '{tone}' tone resonates well — it gets {pct}% more engagement. Consider using it.",
                    confidence=_confidence_from_sample(n, effect_size),
                    sample_size=n,
                    evidence={"tone": tone, "avg_score": round(avg, 1), "overall_avg": round(overall_avg, 1)},
                )
                created += c
                updated += u
                superseded += s
            elif ratio <= 0.7:
                pct = round((1.0 - ratio) * 100)
                c, u, s = self._create_or_update_insight(
                    category=InsightCategory.TONE,
                    source=InsightSource.PERFORMANCE_ANALYSIS,
                    insight_text=f"'{tone}' tone underperforms average by {pct}%",
                    prompt_directive=f"The '{tone}' tone tends to underperform — consider a different tone.",
                    confidence=_confidence_from_sample(n, effect_size),
                    sample_size=n,
                    evidence={"tone": tone, "avg_score": round(avg, 1), "overall_avg": round(overall_avg, 1)},
                )
                created += c
                updated += u
                superseded += s

        return (created, updated, superseded)

    def analyze_template_performance(self) -> tuple[int, int, int]:
        """Generate insights for top and bottom performing templates."""
        rows = self._get_posted_with_performance()
        if not rows:
            return (0, 0, 0)

        by_template: dict[str, list[float]] = defaultdict(list)
        for post, perf in rows:
            if post.template_name:
                by_template[post.template_name].append(_engagement_score(perf))

        if len(by_template) < 2:
            return (0, 0, 0)

        overall_avg = sum(s for scores in by_template.values() for s in scores) / max(
            sum(len(s) for s in by_template.values()), 1
        )

        created, updated, superseded = 0, 0, 0
        for template, scores in by_template.items():
            avg = sum(scores) / len(scores)
            n = len(scores)
            if n < 3:
                continue

            ratio = avg / overall_avg if overall_avg > 0 else 1.0
            effect_size = abs(ratio - 1.0)

            if ratio >= 1.2:
                pct = round((ratio - 1.0) * 100)
                c, u, s = self._create_or_update_insight(
                    category=InsightCategory.TEMPLATE,
                    source=InsightSource.PERFORMANCE_ANALYSIS,
                    insight_text=f"'{template}' template outperforms by {pct}% (avg {avg:.0f})",
                    prompt_directive=f"The '{template}' template structure works well — it gets {pct}% more engagement.",
                    confidence=_confidence_from_sample(n, effect_size),
                    sample_size=n,
                    evidence={"template": template, "avg_score": round(avg, 1), "overall_avg": round(overall_avg, 1), "ratio": round(ratio, 3)},
                )
                created += c
                updated += u
                superseded += s

        return (created, updated, superseded)

    def analyze_topic_performance(self) -> tuple[int, int, int]:
        """Identify which topic keywords drive or hurt engagement."""
        rows = self._get_posted_with_performance()
        if not rows:
            return (0, 0, 0)

        # Map topics to broad categories using keywords
        topic_keywords = {
            "CRO": ["cro", "conversion", "landing page", "a/b test", "aov", "checkout"],
            "Email/SMS": ["email", "sms", "klaviyo", "flow", "campaign", "retention"],
            "Paid Ads": ["ads", "meta", "facebook", "tiktok", "roas", "media buying", "paid"],
            "Amazon": ["amazon", "ppc", "marketplace", "listing"],
            "Shopify": ["shopify", "store", "theme", "app"],
            "Agency": ["agency", "client", "founder", "team", "hiring", "scaling"],
            "AI/Tech": ["ai", "automation", "tool", "chatgpt", "perplexity"],
        }

        by_category: dict[str, list[float]] = defaultdict(list)
        for post, perf in rows:
            topic = (post.topic or "").lower()
            content = (post.content or "").lower()
            combined = f"{topic} {content}"
            score = _engagement_score(perf)
            matched = False
            for cat, keywords in topic_keywords.items():
                if any(kw in combined for kw in keywords):
                    by_category[cat].append(score)
                    matched = True
            if not matched:
                by_category["Other"].append(score)

        if len(by_category) < 2:
            return (0, 0, 0)

        overall_avg = sum(s for scores in by_category.values() for s in scores) / max(
            sum(len(s) for s in by_category.values()), 1
        )

        created, updated, superseded = 0, 0, 0
        for cat, scores in by_category.items():
            avg = sum(scores) / len(scores)
            n = len(scores)
            if n < 3 or cat == "Other":
                continue

            ratio = avg / overall_avg if overall_avg > 0 else 1.0
            effect_size = abs(ratio - 1.0)

            if ratio >= 1.2:
                pct = round((ratio - 1.0) * 100)
                c, u, s = self._create_or_update_insight(
                    category=InsightCategory.TOPIC,
                    source=InsightSource.PERFORMANCE_ANALYSIS,
                    insight_text=f"{cat} topics outperform average by {pct}%",
                    prompt_directive=f"Posts about {cat} perform well — {pct}% above average engagement.",
                    confidence=_confidence_from_sample(n, effect_size),
                    sample_size=n,
                    evidence={"topic_category": cat, "avg_score": round(avg, 1), "overall_avg": round(overall_avg, 1)},
                )
                created += c
                updated += u
                superseded += s
            elif ratio <= 0.7:
                pct = round((1.0 - ratio) * 100)
                c, u, s = self._create_or_update_insight(
                    category=InsightCategory.TOPIC,
                    source=InsightSource.PERFORMANCE_ANALYSIS,
                    insight_text=f"{cat} topics underperform average by {pct}%",
                    prompt_directive=f"Posts about {cat} tend to underperform. Add a unique angle or personal story to make them stand out.",
                    confidence=_confidence_from_sample(n, effect_size),
                    sample_size=n,
                    evidence={"topic_category": cat, "avg_score": round(avg, 1), "overall_avg": round(overall_avg, 1)},
                )
                created += c
                updated += u
                superseded += s

        return (created, updated, superseded)

    def analyze_length_performance(self) -> tuple[int, int, int]:
        """Find the word count sweet spot from actual data."""
        rows = self._get_posted_with_performance()
        if not rows:
            return (0, 0, 0)

        # Bucket by word count ranges
        buckets = {
            "100-150": (100, 150),
            "150-200": (150, 200),
            "200-250": (200, 250),
            "250+": (250, 9999),
        }

        by_bucket: dict[str, list[float]] = defaultdict(list)
        for post, perf in rows:
            wc = post.word_count or len((post.content or "").split())
            for label, (lo, hi) in buckets.items():
                if lo <= wc < hi:
                    by_bucket[label].append(_engagement_score(perf))
                    break

        if len(by_bucket) < 2:
            return (0, 0, 0)

        # Find best bucket
        best_label = None
        best_avg = 0
        total_scores = []
        for label, scores in by_bucket.items():
            total_scores.extend(scores)
            if len(scores) >= 3:
                avg = sum(scores) / len(scores)
                if avg > best_avg:
                    best_avg = avg
                    best_label = label

        if not best_label:
            return (0, 0, 0)

        overall_avg = sum(total_scores) / len(total_scores) if total_scores else 0
        n = len(by_bucket[best_label])
        ratio = best_avg / overall_avg if overall_avg > 0 else 1.0

        if ratio >= 1.1:
            pct = round((ratio - 1.0) * 100)
            return self._create_or_update_insight(
                category=InsightCategory.LENGTH,
                source=InsightSource.PERFORMANCE_ANALYSIS,
                insight_text=f"Posts in the {best_label} word range perform {pct}% above average",
                prompt_directive=f"Target the {best_label} word range — it gets {pct}% more engagement.",
                confidence=_confidence_from_sample(n, abs(ratio - 1.0)),
                sample_size=n,
                evidence={"best_bucket": best_label, "avg_score": round(best_avg, 1), "overall_avg": round(overall_avg, 1)},
            )

        return (0, 0, 0)

    def analyze_timing_performance(self) -> tuple[int, int, int]:
        """Day-of-week engagement analysis."""
        rows = self._get_posted_with_performance()
        if not rows:
            return (0, 0, 0)

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        by_day: dict[int, list[float]] = defaultdict(list)
        for post, perf in rows:
            if post.posted_at:
                by_day[post.posted_at.weekday()].append(_engagement_score(perf))

        if len(by_day) < 2:
            return (0, 0, 0)

        overall_avg = sum(s for scores in by_day.values() for s in scores) / max(
            sum(len(s) for s in by_day.values()), 1
        )

        # Find best day
        best_day = None
        best_avg = 0
        best_n = 0
        for day, scores in by_day.items():
            if len(scores) >= 3:
                avg = sum(scores) / len(scores)
                if avg > best_avg:
                    best_avg = avg
                    best_day = day
                    best_n = len(scores)

        if best_day is None:
            return (0, 0, 0)

        ratio = best_avg / overall_avg if overall_avg > 0 else 1.0
        if ratio >= 1.15:
            pct = round((ratio - 1.0) * 100)
            day_name = day_names[best_day]
            return self._create_or_update_insight(
                category=InsightCategory.TIMING,
                source=InsightSource.PERFORMANCE_ANALYSIS,
                insight_text=f"{day_name} posts outperform average by {pct}%",
                prompt_directive=f"Posts on {day_name} get {pct}% more engagement — optimize content quality for this day.",
                confidence=_confidence_from_sample(best_n, abs(ratio - 1.0)),
                sample_size=best_n,
                evidence={"best_day": day_name, "avg_score": round(best_avg, 1), "overall_avg": round(overall_avg, 1)},
            )

        return (0, 0, 0)

    def analyze_rejection_patterns(self) -> tuple[int, int, int]:
        """Aggregate rejection reasons into actionable avoidance directives."""
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        rejected = (
            self.db.query(QueuedPost)
            .filter(
                QueuedPost.status == PostStatus.REJECTED,
                QueuedPost.updated_at >= thirty_days_ago,
            )
            .all()
        )

        if len(rejected) < 3:
            return (0, 0, 0)

        # Count structured categories
        category_counts: dict[str, int] = defaultdict(int)
        for post in rejected:
            if post.rejection_categories:
                try:
                    cats = json.loads(post.rejection_categories)
                    for cat in cats:
                        category_counts[cat] += 1
                except (json.JSONDecodeError, TypeError):
                    pass

        # Also scan free-text reasons
        keyword_map = {
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
                for keyword, cat in keyword_map.items():
                    if keyword in reason_lower:
                        category_counts[cat] += 1

        if not category_counts:
            return (0, 0, 0)

        labels = {
            "hook_too_weak": ("Weak hooks", "Write stronger scroll-stopping first lines. Previous hooks were too weak."),
            "off_brand": ("Off-brand content", "Stay on-brand as an agency owner helping e-commerce brands scale."),
            "too_generic": ("Generic advice", "Include specific numbers, brand examples, or case study details. Avoid vague advice."),
            "too_long": ("Too long", "Keep posts more concise. Recent long posts were rejected."),
            "too_short": ("Too short", "Add more depth and detail. Recent short posts were rejected."),
            "not_actionable": ("Not actionable", "Include concrete steps or tactics the reader can use immediately."),
            "wrong_tone": ("Wrong tone", "Match the tone to the topic and audience. Recent tone mismatches were rejected."),
            "wrong_topic": ("Wrong topic", "Focus on core content pillars: CRO, Klaviyo, e-commerce growth, Shopify, Amazon, agency lessons."),
            "factually_wrong": ("Factual errors", "Double-check all claims, statistics, and numbers for accuracy."),
            "sounds_ai": ("AI-sounding", "Write more naturally. Include personal stories, specific details, and conversational language."),
        }

        created, updated, superseded = 0, 0, 0
        for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
            if count < 2:
                continue
            label, directive = labels.get(cat, (cat.replace("_", " ").title(), f"Avoid {cat.replace('_', ' ')} patterns."))
            c, u, s = self._create_or_update_insight(
                category=InsightCategory.REJECTION_PATTERN,
                source=InsightSource.REJECTION_ANALYSIS,
                insight_text=f"{label}: rejected {count}x in last 30 days",
                prompt_directive=directive,
                confidence=_confidence_from_sample(count),
                sample_size=count,
                evidence={"rejection_category": cat, "count": count, "period_days": 30},
            )
            created += c
            updated += u
            superseded += s

        return (created, updated, superseded)

    def analyze_edit_patterns(self) -> tuple[int, int, int]:
        """Analyze what users change when they edit posts before approving."""
        edited_posts = (
            self.db.query(QueuedPost)
            .filter(
                QueuedPost.status.in_([PostStatus.APPROVED, PostStatus.POSTED, PostStatus.SCHEDULED]),
                QueuedPost.user_edits != None,
                QueuedPost.user_edits != "",
            )
            .all()
        )

        if len(edited_posts) < 3:
            return (0, 0, 0)

        # Analyze edit patterns
        length_changes = []  # positive = shortened, negative = lengthened
        for post in edited_posts:
            original_words = len((post.content or "").split())
            edited_words = len((post.user_edits or "").split())
            if original_words > 0:
                change_pct = ((original_words - edited_words) / original_words) * 100
                length_changes.append(change_pct)

        created, updated, superseded = 0, 0, 0

        if length_changes:
            avg_change = sum(length_changes) / len(length_changes)
            n = len(length_changes)

            if avg_change > 10:
                # User consistently shortens posts
                c, u, s = self._create_or_update_insight(
                    category=InsightCategory.EDIT_PATTERN,
                    source=InsightSource.EDIT_ANALYSIS,
                    insight_text=f"You shorten posts by avg {avg_change:.0f}% when editing — write more concisely",
                    prompt_directive=f"Write more concisely. Posts are typically shortened by {avg_change:.0f}% during review.",
                    confidence=_confidence_from_sample(n),
                    sample_size=n,
                    evidence={"avg_shortening_pct": round(avg_change, 1), "edited_count": n},
                )
                created += c
                updated += u
                superseded += s
            elif avg_change < -10:
                # User consistently lengthens posts
                abs_change = abs(avg_change)
                c, u, s = self._create_or_update_insight(
                    category=InsightCategory.EDIT_PATTERN,
                    source=InsightSource.EDIT_ANALYSIS,
                    insight_text=f"You expand posts by avg {abs_change:.0f}% when editing — add more detail",
                    prompt_directive=f"Add more depth and detail. Posts are typically expanded by {abs_change:.0f}% during review.",
                    confidence=_confidence_from_sample(n),
                    sample_size=n,
                    evidence={"avg_expansion_pct": round(abs_change, 1), "edited_count": n},
                )
                created += c
                updated += u
                superseded += s

        return (created, updated, superseded)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_posted_with_performance(self) -> list[tuple[QueuedPost, PostPerformance]]:
        """Get all posted posts that have performance data (cached per analysis run)."""
        if self._cached_posted_rows is None:
            self._cached_posted_rows = (
                self.db.query(QueuedPost, PostPerformance)
                .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
                .filter(QueuedPost.status == PostStatus.POSTED)
                .all()
            )
        return self._cached_posted_rows

    def _extract_tone(self, prompt: str | None) -> str | None:
        """Extract tone from a generation prompt string."""
        if not prompt:
            return None
        match = re.search(r"TONE:[ \t]*([^\n]+)", prompt)
        if match:
            return match.group(1).strip().lower()
        return None

    def analyze_research_performance(self) -> tuple[int, int, int]:
        """Compare engagement of research-sourced vs non-research posts."""
        research_rows = (
            self.db.query(QueuedPost, PostPerformance)
            .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
            .filter(
                QueuedPost.status == PostStatus.POSTED,
                QueuedPost.research_item_id.isnot(None),
            )
            .all()
        )
        non_research_rows = (
            self.db.query(QueuedPost, PostPerformance)
            .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
            .filter(
                QueuedPost.status == PostStatus.POSTED,
                QueuedPost.research_item_id.is_(None),
            )
            .all()
        )

        if len(research_rows) < 3 or len(non_research_rows) < 3:
            return (0, 0, 0)

        research_scores = [_engagement_score(p) for _, p in research_rows]
        non_research_scores = [_engagement_score(p) for _, p in non_research_rows]

        research_avg = sum(research_scores) / len(research_scores)
        non_research_avg = sum(non_research_scores) / len(non_research_scores)

        if non_research_avg == 0:
            return (0, 0, 0)

        ratio = research_avg / non_research_avg
        n = len(research_rows)

        if ratio >= 1.15:
            pct = round((ratio - 1.0) * 100)
            return self._create_or_update_insight(
                category=InsightCategory.TOPIC,
                source=InsightSource.PERFORMANCE_ANALYSIS,
                insight_text=f"Research-based posts outperform by {pct}% (avg {research_avg:.0f} vs {non_research_avg:.0f})",
                prompt_directive=f"Prioritize research-sourced topics — they get {pct}% more engagement than ad-hoc topics.",
                confidence=_confidence_from_sample(n, abs(ratio - 1.0)),
                sample_size=n,
                evidence={
                    "topic_category": "research_sourced",
                    "research_avg": round(research_avg, 1),
                    "non_research_avg": round(non_research_avg, 1),
                    "ratio": round(ratio, 2),
                },
            )
        elif ratio <= 0.85:
            pct = round((1.0 - ratio) * 100)
            return self._create_or_update_insight(
                category=InsightCategory.TOPIC,
                source=InsightSource.PERFORMANCE_ANALYSIS,
                insight_text=f"Research-based posts underperform by {pct}% — add unique personal angles",
                prompt_directive=f"Research-sourced topics are underperforming by {pct}%. Focus on adding unique personal angles to research topics.",
                confidence=_confidence_from_sample(n, abs(ratio - 1.0)),
                sample_size=n,
                evidence={
                    "topic_category": "research_sourced",
                    "research_avg": round(research_avg, 1),
                    "non_research_avg": round(non_research_avg, 1),
                    "ratio": round(ratio, 2),
                },
            )

        return (0, 0, 0)

    def _create_or_update_insight(
        self,
        category: InsightCategory,
        source: InsightSource,
        insight_text: str,
        prompt_directive: str,
        confidence: float,
        sample_size: int,
        evidence: dict,
    ) -> tuple[int, int, int]:
        """Create a new insight or update/supersede an existing one.

        Returns (created, updated, superseded) counts.
        """
        # Look for existing active insight in same category from same source
        existing = (
            self.db.query(LearningInsight)
            .filter(
                LearningInsight.category == category,
                LearningInsight.source == source,
                LearningInsight.is_active == True,
            )
            .all()
        )

        # Check if there's an insight about the same subject
        # (e.g., same hook_type, same tone, same template)
        subject_key = self._extract_subject_key(evidence)

        for ex in existing:
            ex_key = self._extract_subject_key(
                json.loads(ex.evidence_json) if ex.evidence_json else {}
            )
            if ex_key and ex_key == subject_key:
                # Same subject — update if we have better data
                if confidence >= ex.confidence or sample_size > (ex.sample_size or 0):
                    ex.insight_text = insight_text
                    ex.prompt_directive = prompt_directive
                    ex.confidence = confidence
                    ex.sample_size = sample_size
                    ex.evidence_json = json.dumps(evidence)
                    ex.updated_at = datetime.utcnow()
                    self.db.commit()
                    return (0, 1, 0)
                else:
                    # Existing insight is stronger — skip
                    return (0, 0, 0)

        # No matching existing insight — create new
        insight = LearningInsight(
            category=category,
            source=source,
            insight_text=insight_text,
            prompt_directive=prompt_directive,
            confidence=confidence,
            sample_size=sample_size,
            evidence_json=json.dumps(evidence),
            is_active=True,
        )
        self.db.add(insight)
        self.db.commit()
        return (1, 0, 0)

    def analyze_media_type_performance(self) -> tuple[int, int, int]:
        """Compare engagement by media type (text-only vs image vs gif/video)."""
        posts_with_perf = (
            self.db.query(QueuedPost, PostPerformance)
            .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
            .filter(QueuedPost.status == PostStatus.POSTED)
            .all()
        )

        if not posts_with_perf:
            return (0, 0, 0)

        by_media: dict[str, list[float]] = defaultdict(list)
        for post, perf in posts_with_perf:
            score = _engagement_score(perf)
            if post.has_image:
                by_media["image"].append(score)
            elif post.has_video:
                by_media["video"].append(score)
            else:
                by_media["text"].append(score)

        if len(by_media) < 2:
            return (0, 0, 0)

        # Find best and worst
        avgs = {k: sum(v) / len(v) for k, v in by_media.items() if v}
        if not avgs:
            return (0, 0, 0)

        best_type = max(avgs, key=avgs.get)
        best_avg = avgs[best_type]
        overall_avg = sum(s for scores in by_media.values() for s in scores) / sum(len(v) for v in by_media.values())

        if best_avg <= overall_avg * 1.2:
            return (0, 0, 0)

        total_n = sum(len(v) for v in by_media.values())
        return self._create_or_update_insight(
            category=InsightCategory.GENERAL,
            source=InsightSource.PERFORMANCE_ANALYSIS,
            insight_text=(
                f"'{best_type}' posts average {best_avg:.0f} engagement vs {overall_avg:.0f} overall "
                f"({best_avg / overall_avg:.1f}x). Based on {total_n} posts."
            ),
            prompt_directive=(
                f"Use {best_type}-only format — it outperforms other formats by "
                f"{best_avg / overall_avg:.1f}x for this account."
            ),
            confidence=_confidence_from_sample(total_n, best_avg / overall_avg - 1),
            sample_size=total_n,
            evidence={"best_type": best_type, "avg_by_type": {k: round(v, 1) for k, v in avgs.items()}},
        )

    def analyze_time_of_day_performance(self) -> tuple[int, int, int]:
        """Analyze which hour-of-day windows produce the best engagement."""
        posts_with_perf = (
            self.db.query(QueuedPost, PostPerformance)
            .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
            .filter(
                QueuedPost.status == PostStatus.POSTED,
                QueuedPost.posted_at.isnot(None),
            )
            .all()
        )

        if not posts_with_perf:
            return (0, 0, 0)

        # Bucket by 2-hour windows
        buckets: dict[str, list[float]] = defaultdict(list)
        for post, perf in posts_with_perf:
            if not post.posted_at:
                continue
            hour = post.posted_at.hour
            if hour < 8:
                bucket = "early_morning_before_8"
            elif hour < 10:
                bucket = "morning_8_to_10"
            elif hour < 12:
                bucket = "late_morning_10_to_12"
            elif hour < 14:
                bucket = "afternoon_12_to_14"
            elif hour < 17:
                bucket = "afternoon_14_to_17"
            else:
                bucket = "evening_after_17"
            buckets[bucket].append(_engagement_score(perf))

        if len(buckets) < 2:
            return (0, 0, 0)

        avgs = {k: sum(v) / len(v) for k, v in buckets.items() if v}
        best_bucket = max(avgs, key=avgs.get)
        best_avg = avgs[best_bucket]
        overall_avg = sum(s for scores in buckets.values() for s in scores) / sum(len(v) for v in buckets.values())

        if best_avg <= overall_avg * 1.3:
            return (0, 0, 0)

        total_n = sum(len(v) for v in buckets.values())
        readable = best_bucket.replace("_", " ")
        return self._create_or_update_insight(
            category=InsightCategory.TIMING,
            source=InsightSource.PERFORMANCE_ANALYSIS,
            insight_text=(
                f"Posts published during '{readable}' average {best_avg:.0f} engagement "
                f"vs {overall_avg:.0f} overall ({best_avg / overall_avg:.1f}x). Based on {total_n} posts."
            ),
            prompt_directive=(
                f"Post during the '{readable}' window for maximum reach — "
                f"it outperforms other times by {best_avg / overall_avg:.1f}x."
            ),
            confidence=_confidence_from_sample(total_n, best_avg / overall_avg - 1),
            sample_size=total_n,
            evidence={"best_bucket": best_bucket, "avg_by_bucket": {k: round(v, 1) for k, v in avgs.items()}},
        )

    def analyze_prediction_accuracy(self) -> tuple[int, int, int]:
        """Compare virality scores (predicted) vs actual engagement for autoresearch calibration.

        Runs calibration via autoresearch.log and generates an insight if there's
        a consistent bias in the prediction.
        """
        try:
            from autoresearch.log import ExperimentLog
        except ImportError:
            return (0, 0, 0)

        experiment_log = ExperimentLog(self.db)
        entries = experiment_log.calibrate()

        if len(entries) < 3:
            return (0, 0, 0)

        # Also update program.md win rates
        experiment_log.update_program_win_rates()
        experiment_log.update_program_calibration()

        # Analyze bias: is the scorer consistently over or under-predicting?
        deltas = [e["delta"] for e in entries]
        avg_delta = sum(deltas) / len(deltas)

        # Update virality scorer calibration offset
        if abs(avg_delta) > 5:
            try:
                from content.virality_scorer import ViralityScorer
                # Positive delta = scorer over-predicts, so offset subtracts
                ViralityScorer.save_calibration_offset(round(avg_delta))
            except Exception as e:
                logger.warning("Failed to save calibration offset: %s", e)

        if abs(avg_delta) > 10:
            direction = "over" if avg_delta > 0 else "under"
            return self._create_or_update_insight(
                category=InsightCategory.GENERAL,
                source=InsightSource.PERFORMANCE_ANALYSIS,
                insight_text=(
                    f"Virality scorer {direction}-predicts by {abs(avg_delta):.0f} points on average "
                    f"(based on {len(entries)} experiments with real engagement data)."
                ),
                prompt_directive=(
                    f"Note: the virality scorer tends to {direction}-predict engagement by ~{abs(avg_delta):.0f} points. "
                    f"{'Aim higher than the score suggests.' if direction == 'over' else 'Posts may perform better than expected.'}"
                ),
                confidence=_confidence_from_sample(len(entries)),
                sample_size=len(entries),
                evidence={"avg_delta": round(avg_delta, 1), "entries": len(entries), "direction": direction},
            )

        return (0, 0, 0)

    def _extract_subject_key(self, evidence: dict) -> str | None:
        """Extract a subject key from evidence for dedup.

        E.g., "hook_type:question" or "tone:vulnerable".
        """
        for key in ("hook_type", "tone", "template", "topic_category", "best_bucket", "best_day", "rejection_category"):
            if key in evidence:
                return f"{key}:{evidence[key]}"
        # For edit patterns, use a generic key
        if "avg_shortening_pct" in evidence or "avg_expansion_pct" in evidence:
            return "edit:length_change"
        return None
