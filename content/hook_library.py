"""Hook library — accumulates winning hooks from top-performing posts.

Extracts hooks from own posts and competitor posts, stores them in the
hook_library DB table, and provides topic-relevant hooks for prompt injection.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from database.models import (
    CompetitorPost,
    HookEntry,
    MyLinkedInPost,
    PostPerformance,
    PostStatus,
    QueuedPost,
)

logger = logging.getLogger(__name__)


def _extract_hook_text(content: str) -> str:
    """Extract the hook (first 1-3 lines before a blank line) from post content."""
    if not content:
        return ""
    lines = content.strip().split("\n")
    hook_lines = []
    for line in lines:
        if line.strip() == "" and hook_lines:
            break
        if line.strip():
            hook_lines.append(line.strip())
        if len(hook_lines) >= 3:
            break
    return "\n".join(hook_lines)


def _classify_hook_type(hook_text: str) -> str:
    """Classify a hook into a type based on its structure."""
    lower = hook_text.lower()
    if lower.startswith(("i ", "i'", "my ", "we ", "our ")):
        return "story"
    if "?" in hook_text:
        return "question"
    if any(c.isdigit() for c in hook_text[:50]):
        return "statistic"
    if any(lower.startswith(w) for w in ["stop ", "don't ", "never ", "quit "]):
        return "command"
    if any(phrase in lower for phrase in ["everyone says", "they're wrong", "unpopular opinion", "hot take"]):
        return "contrarian"
    return "statement"


class HookLibrary:
    """Manages the hook library — extraction, storage, and retrieval."""

    def __init__(self, db: Session):
        self.db = db

    def extract_from_top_posts(self, min_engagement: int = 50) -> int:
        """Extract hooks from own top-performing posted content.

        Returns the number of new hooks added.
        """
        top_posts = (
            self.db.query(QueuedPost, PostPerformance)
            .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
            .filter(QueuedPost.status == PostStatus.POSTED)
            .all()
        )

        added = 0
        for post, perf in top_posts:
            score = (perf.likes or 0) + (perf.comments or 0) * 3 + (perf.shares or 0) * 5
            if score < min_engagement:
                continue

            hook_text = post.hook or _extract_hook_text(post.content)
            if not hook_text or len(hook_text) < 10:
                continue

            # Skip if already in library
            existing = (
                self.db.query(HookEntry)
                .filter(HookEntry.source_post_id == post.id, HookEntry.source == "own")
                .first()
            )
            if existing:
                existing.engagement_score = score
                continue

            entry = HookEntry(
                text=hook_text,
                hook_type=post.hook_type or _classify_hook_type(hook_text),
                source="own",
                source_post_id=post.id,
                engagement_score=score,
                topic_category=post.topic,
            )
            self.db.add(entry)
            added += 1

        self.db.commit()
        logger.info("Extracted %d hooks from top own posts", added)
        return added

    def extract_from_competitors(self, min_likes: int = 100) -> int:
        """Extract hooks from high-performing competitor posts.

        Returns the number of new hooks added.
        """
        top_comp_posts = (
            self.db.query(CompetitorPost)
            .filter(CompetitorPost.likes >= min_likes)
            .all()
        )

        added = 0
        for cp in top_comp_posts:
            if not cp.content:
                continue

            hook_text = _extract_hook_text(cp.content)
            if not hook_text or len(hook_text) < 10:
                continue

            # Skip if already in library
            existing = (
                self.db.query(HookEntry)
                .filter(HookEntry.source_post_id == cp.id, HookEntry.source == "competitor")
                .first()
            )
            if existing:
                existing.engagement_score = cp.likes or 0
                continue

            score = (cp.likes or 0) + (cp.comments or 0) * 3
            entry = HookEntry(
                text=hook_text,
                hook_type=cp.hook_style or _classify_hook_type(hook_text),
                source="competitor",
                source_post_id=cp.id,
                engagement_score=score,
                topic_category=cp.topic or None,
            )
            self.db.add(entry)
            added += 1

        self.db.commit()
        logger.info("Extracted %d hooks from competitor posts", added)
        return added

    def get_hooks_for_topic(self, topic: str, limit: int = 5) -> list[HookEntry]:
        """Retrieve the best hooks relevant to a topic.

        Prioritizes hooks with high engagement scores, preferring own posts
        over competitor posts. Avoids recently-used hooks.
        """
        # Try topic-matched hooks first
        all_hooks = (
            self.db.query(HookEntry)
            .order_by(HookEntry.engagement_score.desc())
            .all()
        )

        if not all_hooks:
            return []

        # Score hooks by relevance to topic
        topic_lower = topic.lower() if topic else ""
        scored = []
        for hook in all_hooks:
            relevance = hook.engagement_score
            # Boost for topic match
            if hook.topic_category and topic_lower:
                cat_lower = hook.topic_category.lower()
                common_words = set(topic_lower.split()) & set(cat_lower.split())
                if common_words:
                    relevance *= 1.5
            # Slight boost for own hooks (more authentic to voice)
            if hook.source == "own":
                relevance *= 1.2
            # Slight penalty for recently used
            if hook.times_used and hook.times_used > 2:
                relevance *= 0.7
            scored.append((hook, relevance))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [hook for hook, _ in scored[:limit]]

    def mark_used(self, hook_ids: list[int]) -> None:
        """Mark hooks as used in a generation prompt."""
        for hook_id in hook_ids:
            hook = self.db.query(HookEntry).filter(HookEntry.id == hook_id).first()
            if hook:
                hook.times_used = (hook.times_used or 0) + 1
                hook.last_used_at = datetime.utcnow()
        self.db.commit()

    def add_manual_hook(self, text: str, hook_type: str = "", topic: str = "") -> HookEntry:
        """Add a hook manually via the dashboard."""
        entry = HookEntry(
            text=text,
            hook_type=hook_type or _classify_hook_type(text),
            source="manual",
            topic_category=topic or None,
            engagement_score=0,
        )
        self.db.add(entry)
        self.db.commit()
        return entry

    def run_extraction(self) -> dict:
        """Run full extraction cycle — own posts + competitors."""
        own_count = self.extract_from_top_posts()
        comp_count = self.extract_from_competitors()
        total = self.db.query(HookEntry).count()
        return {"own_added": own_count, "competitor_added": comp_count, "total_hooks": total}
