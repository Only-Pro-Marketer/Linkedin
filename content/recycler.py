"""Content recycler — repurpose top-performing posts with fresh variations.

LinkedIn posts have a 2-3 week lifespan. After 60+ days, proven content
can be recycled with new examples, numbers, and phrasing while keeping
the same structure that made the original succeed.
"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import llm
from config import settings
from content.brand import get_niche
from content.post_formatter import format_for_linkedin
from content.prompt_builder import WRITING_RULES
from content.virality_scorer import ViralityScorer
from database.models import PostPerformance, PostStatus, QueuedPost

logger = logging.getLogger(__name__)

RECYCLE_PROMPT = """You are rewriting a LinkedIn post that performed exceptionally well.

ORIGINAL POST (achieved {engagement_score} engagement — {likes} likes, {comments} comments, {shares} shares):
---
{original_content}
---

Original template: {template_name}
Original topic: {topic}

YOUR TASK:
Create a FRESH version of this post that:
1. Covers the SAME topic area with the SAME structural approach
2. Uses DIFFERENT specific examples, numbers, and phrasing
3. Keeps the same hook STYLE (what made people stop scrolling)
4. Keeps the same CTA STYLE (what made people comment)
5. Feels like a natural follow-up, not a copy

RULES:
- Do NOT copy any specific phrases or sentences from the original
- Use new angles or scenarios; only use numbers that are real (from the brand profile) or clearly hypothetical
- Keep the same tone and energy

Output only the rewritten post."""


class ContentRecycler:
    """Recycles top-performing posts by generating fresh variations."""

    def __init__(self, db: Session):
        self.db = db
        self.scorer = ViralityScorer()

    def find_recyclable_posts(
        self,
        min_age_days: int | None = None,
        min_engagement: int | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Find top-performing posts eligible for recycling.

        Returns list of dicts with post info and engagement data.
        """
        if min_age_days is None:
            min_age_days = settings.RECYCLING_MIN_AGE_DAYS
        if min_engagement is None:
            min_engagement = settings.RECYCLING_MIN_ENGAGEMENT

        cutoff = datetime.utcnow() - timedelta(days=min_age_days)

        candidates = (
            self.db.query(QueuedPost, PostPerformance)
            .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
            .filter(
                QueuedPost.status == PostStatus.POSTED,
                QueuedPost.posted_at <= cutoff,
                QueuedPost.posted_at.isnot(None),
            )
            .all()
        )

        results = []
        for post, perf in candidates:
            score = (perf.likes or 0) + (perf.comments or 0) * 3 + (perf.shares or 0) * 5
            if score < min_engagement:
                continue

            # Count how many times this post has been recycled
            recycle_count = (
                self.db.query(QueuedPost)
                .filter(QueuedPost.recycled_from_id == post.id)
                .count()
            )

            results.append({
                "id": post.id,
                "content": post.content,
                "template_name": post.template_name,
                "topic": post.topic,
                "posted_at": post.posted_at.isoformat() if post.posted_at else None,
                "likes": perf.likes or 0,
                "comments": perf.comments or 0,
                "shares": perf.shares or 0,
                "engagement_score": score,
                "recycle_count": recycle_count,
            })

        results.sort(key=lambda x: x["engagement_score"], reverse=True)
        return results[:limit]

    def recycle_post(self, post_id: int) -> dict:
        """Generate a fresh version of a top-performing post.

        Returns dict with the new post info or error.
        """
        original = self.db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
        if not original:
            return {"error": "Post not found"}

        perf = (
            self.db.query(PostPerformance)
            .filter(PostPerformance.post_id == post_id)
            .first()
        )

        likes = perf.likes or 0 if perf else 0
        comments = perf.comments or 0 if perf else 0
        shares = perf.shares or 0 if perf else 0
        engagement_score = likes + comments * 3 + shares * 5

        prompt = RECYCLE_PROMPT.format(
            original_content=original.content,
            template_name=original.template_name or "unknown",
            topic=original.topic or get_niche(),
            engagement_score=engagement_score,
            likes=likes,
            comments=comments,
            shares=shares,
        )

        try:
            content = llm.complete("recycle", prompt, packs=("post",), instructions=WRITING_RULES).text
        except llm.LLMError as e:
            return {"error": str(e)}

        from content.pipeline import create_queued_post

        new_post = create_queued_post(
            self.db, content, topic=original.topic or "", source="recycle",
            template_name=original.template_name, recycled_from_id=original.id,
            formula_id=original.formula_id, goal=original.goal,
        )
        logger.info("Recycled post #%d → new post #%d", post_id, new_post.id)
        return {
            "new_post_id": new_post.id,
            "original_post_id": post_id,
            "virality_score": new_post.virality_score,
            "quality_score": new_post.quality_score,
            "content_preview": new_post.content[:150],
        }
