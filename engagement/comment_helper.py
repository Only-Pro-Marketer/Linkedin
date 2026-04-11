"""Comment helper — assists with strategic commenting on industry leaders' posts.

Strategic commenting (10-15 thoughtful comments/day) is the #1 growth lever
for LinkedIn in 2025-2026. Comments are 15x more valuable than reactions.
This module helps by surfacing target posts and drafting value-adding comments.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from config import settings, get_anthropic_client
from database.models import Competitor, CompetitorPost

# Load soul.md for brand-aware commenting
_SOUL_PATH = Path(__file__).resolve().parent.parent / "soul" / "soul.md"
_soul_content = ""
if _SOUL_PATH.exists():
    _soul_content = _SOUL_PATH.read_text(encoding="utf-8")

logger = logging.getLogger(__name__)

COMMENT_DRAFT_PROMPT = """You are writing a thoughtful comment on someone else's LinkedIn post to build genuine engagement and visibility.

Write from the perspective described in this brand profile:
---
{soul_context}
---

THE POST YOU ARE COMMENTING ON:
---
{post_content}
---

Author: {author_name}
Topic area: {topic}

WRITE A COMMENT THAT:
1. References a SPECIFIC point from the post (not generic "great post!" praise)
2. Adds genuine value — share a relevant experience, data point, or insight from your work
3. Is 2-4 sentences long (long enough to trigger dwell time, short enough to not hijack)
4. Ends with a question or insight that invites further discussion
5. Sounds authentic to the brand voice described above
6. Does NOT sell or self-promote — pure value addition

BAD EXAMPLES (never write these):
- "Great post! Totally agree."
- "This is so true! Check out my company for more."
- "Love this! We do the same thing."

GOOD EXAMPLE STYLE:
"Interesting point about email frequency. We tested this across 12 accounts last quarter — the sweet spot varied significantly by industry. The product consideration cycle seems to matter more than the industry average suggests. Have you seen similar patterns?"

OUTPUT:
Provide ONLY the comment text. No quotes, no explanations."""


class CommentHelper:
    """Assists with strategic commenting on competitor/industry leader posts."""

    def __init__(self, db: Session):
        self.db = db
        self.client = get_anthropic_client()

    def get_daily_targets(self, count: int = 15) -> list[dict]:
        """Get high-engagement competitor posts worth commenting on today.

        Prioritizes: recent + high engagement + not yet commented on.
        Returns list of dicts with post info and competitor name.
        """
        seven_days_ago = datetime.utcnow() - timedelta(days=7)

        targets = (
            self.db.query(CompetitorPost, Competitor)
            .join(Competitor, CompetitorPost.competitor_id == Competitor.id)
            .filter(
                CompetitorPost.commented_at.is_(None),
                CompetitorPost.content.isnot(None),
                CompetitorPost.post_date >= seven_days_ago,
                Competitor.is_active == True,
            )
            .order_by(
                (CompetitorPost.likes + CompetitorPost.comments * 3).desc()
            )
            .limit(count * 2)  # fetch extra for filtering
            .all()
        )

        results = []
        for cp, comp in targets:
            if not cp.content or len(cp.content.strip()) < 50:
                continue
            results.append({
                "id": cp.id,
                "competitor_name": comp.name,
                "content": cp.content,
                "content_preview": cp.content[:200] + "..." if len(cp.content) > 200 else cp.content,
                "post_url": cp.post_url,
                "likes": cp.likes or 0,
                "comments": cp.comments or 0,
                "topic": cp.topic,
                "hook_style": cp.hook_style,
                "post_date": cp.post_date.isoformat() if cp.post_date else None,
                "comment_draft": cp.comment_draft,
            })
            if len(results) >= count:
                break

        return results

    def draft_comment(self, competitor_post_id: int) -> dict:
        """Generate a thoughtful comment draft for a competitor post.

        Returns dict with the draft or error.
        """
        cp = self.db.query(CompetitorPost).filter(CompetitorPost.id == competitor_post_id).first()
        if not cp:
            return {"error": "Post not found"}

        comp = self.db.query(Competitor).filter(Competitor.id == cp.competitor_id).first()
        author_name = comp.name if comp else "Unknown"

        prompt = COMMENT_DRAFT_PROMPT.format(
            soul_context=_soul_content[:500] if _soul_content else "No brand profile configured",
            post_content=cp.content[:2000],
            author_name=author_name,
            topic=cp.topic or "marketing / e-commerce",
        )

        try:
            message = self.client.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=300,
                temperature=0.7,
                messages=[{"role": "user", "content": prompt}],
            )
            draft = message.content[0].text.strip()
        except Exception as e:
            logger.error("Failed to draft comment: %s", e)
            return {"error": f"Generation failed: {e}"}

        # Save draft to DB
        cp.comment_draft = draft
        self.db.commit()

        return {
            "post_id": competitor_post_id,
            "draft": draft,
            "author": author_name,
            "post_url": cp.post_url,
        }

    def mark_commented(self, competitor_post_id: int) -> bool:
        """Mark a post as commented on."""
        cp = self.db.query(CompetitorPost).filter(CompetitorPost.id == competitor_post_id).first()
        if not cp:
            return False
        cp.commented_at = datetime.utcnow()
        self.db.commit()
        return True

    def get_commenting_stats(self) -> dict:
        """Get commenting activity stats."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        this_week = today - timedelta(days=today.weekday())

        today_count = (
            self.db.query(CompetitorPost)
            .filter(CompetitorPost.commented_at >= today)
            .count()
        )
        week_count = (
            self.db.query(CompetitorPost)
            .filter(CompetitorPost.commented_at >= this_week)
            .count()
        )
        total_count = (
            self.db.query(CompetitorPost)
            .filter(CompetitorPost.commented_at.isnot(None))
            .count()
        )

        return {
            "today": today_count,
            "this_week": week_count,
            "total": total_count,
            "daily_target": 15,
            "today_remaining": max(0, 15 - today_count),
        }
