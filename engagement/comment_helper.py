"""Comment helper — surfaces competitor posts worth commenting on and drafts comments.

Thoughtful comments on other people's posts are one of the strongest growth
levers on LinkedIn. Drafts follow the comment playbook in knowledge/.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

import llm
from database.models import Competitor, CompetitorPost

logger = logging.getLogger(__name__)

DAILY_TARGET = 15

COMMENT_RULES = """You write comments on other people's LinkedIn posts for the author in <brand_voice>, following comment-templates.md and voice-rules.md.

A good comment:
- is 200–350 characters, in 1–2 short paragraphs;
- reacts to one specific point from the post (never "Great post!");
- adds one sharp insight, experience or data point the post did not cover;
- ends with a genuine question or a sharper angle that invites a reply;
- never pitches or names the author's own product;
- capitalises names, uses no hashtags.
Output only the comment text."""


class CommentHelper:
    """Assists with strategic commenting on competitor / industry-leader posts."""

    def __init__(self, db: Session):
        self.db = db

    def get_daily_targets(self, count: int = DAILY_TARGET) -> list[dict]:
        """Recent, high-engagement competitor posts not yet commented on."""
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        targets = (
            self.db.query(CompetitorPost, Competitor)
            .join(Competitor, CompetitorPost.competitor_id == Competitor.id)
            .filter(
                CompetitorPost.commented_at.is_(None),
                CompetitorPost.content.isnot(None),
                CompetitorPost.post_date >= seven_days_ago,
                Competitor.is_active == True,  # noqa: E712
            )
            .order_by((CompetitorPost.likes + CompetitorPost.comments * 3).desc())
            .limit(count * 2)
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
        """Generate a comment draft for a competitor post."""
        cp = self.db.query(CompetitorPost).filter(CompetitorPost.id == competitor_post_id).first()
        if not cp:
            return {"error": "Post not found"}
        comp = self.db.query(Competitor).filter(Competitor.id == cp.competitor_id).first()
        author_name = comp.name if comp else "the author"

        user = (f"Write a comment on this post by {author_name}.\n\n"
                f"{llm.untrusted(cp.content[:3000], 'linkedin_post')}")
        try:
            draft = llm.complete("comment_draft", user, packs=("comment",), instructions=COMMENT_RULES,
                                 effort="medium", max_tokens=3000).text
        except llm.LLMError as e:
            return {"error": str(e)}

        cp.comment_draft = draft
        self.db.commit()
        return {"post_id": competitor_post_id, "draft": draft, "author": author_name, "post_url": cp.post_url}

    def mark_commented(self, competitor_post_id: int) -> bool:
        cp = self.db.query(CompetitorPost).filter(CompetitorPost.id == competitor_post_id).first()
        if not cp:
            return False
        cp.commented_at = datetime.utcnow()
        self.db.commit()
        return True

    def get_commenting_stats(self) -> dict:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        this_week = today - timedelta(days=today.weekday())
        q = self.db.query(CompetitorPost)
        today_count = q.filter(CompetitorPost.commented_at >= today).count()
        return {
            "today": today_count,
            "this_week": q.filter(CompetitorPost.commented_at >= this_week).count(),
            "total": q.filter(CompetitorPost.commented_at.isnot(None)).count(),
            "daily_target": DAILY_TARGET,
            "today_remaining": max(0, DAILY_TARGET - today_count),
        }
