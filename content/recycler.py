"""Content recycler — repurpose top-performing posts with fresh variations.

LinkedIn posts have a 2-3 week lifespan. After 60+ days, proven content
can be recycled with new examples, numbers, and phrasing while keeping
the same structure that made the original succeed.
"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from config import settings, get_anthropic_client
from content.post_formatter import format_for_linkedin
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
- Use new data points, client examples, or scenarios
- Keep the same tone and energy
- 150-250 words
- One thought per line with blank lines between
- No markdown, no hashtags
- End with an easy-to-answer question

OUTPUT:
Provide ONLY the rewritten post. No explanations."""


class ContentRecycler:
    """Recycles top-performing posts by generating fresh variations."""

    def __init__(self, db: Session):
        self.db = db
        self.client = get_anthropic_client()
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
            topic=original.topic or "e-commerce growth",
            engagement_score=engagement_score,
            likes=likes,
            comments=comments,
            shares=shares,
        )

        try:
            message = self.client.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=settings.CLAUDE_MAX_TOKENS,
                temperature=settings.CLAUDE_TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )
            content = message.content[0].text.strip()
        except Exception as e:
            logger.error("Claude API error during recycling: %s", e)
            return {"error": f"Generation failed: {e}"}

        content = format_for_linkedin(content, original.topic or "")

        # Score the recycled post
        score_result = self.scorer.score(content, original.topic or "")
        virality_score = score_result.get("total_score", 50)

        # Only queue if it scores reasonably well
        if virality_score < 45:
            logger.info(
                "Recycled post scored too low (%d) — discarding", virality_score
            )
            return {
                "error": f"Recycled post scored {virality_score}/100 — too low to queue",
                "content": content,
                "score": virality_score,
            }

        new_post = QueuedPost(
            content=content,
            template_name=original.template_name,
            topic=original.topic,
            status=PostStatus.QUEUED,
            virality_score=virality_score,
            virality_breakdown=json.dumps(score_result),
            virality_performance=score_result.get("predicted_performance", "medium"),
            recycled_from_id=original.id,
            word_count=len(content.split()),
        )
        self.db.add(new_post)
        self.db.commit()

        logger.info(
            "Recycled post #%d → new post #%d (score: %d)",
            post_id, new_post.id, virality_score,
        )
        return {
            "new_post_id": new_post.id,
            "original_post_id": post_id,
            "virality_score": virality_score,
            "content_preview": content[:150],
        }
