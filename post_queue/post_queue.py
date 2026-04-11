"""Queue management — CRUD operations for the post approval pipeline."""

from datetime import datetime

from sqlalchemy.orm import Session

from database.models import PostStatus, QueuedPost, PostPerformance


class PostQueue:
    """Manages the post approval queue."""

    def __init__(self, db: Session):
        self.db = db

    # ── Read operations ───────────────────────────────────────

    def get_queued(self, limit: int = 50) -> list[QueuedPost]:
        """Get posts waiting for review."""
        return (
            self.db.query(QueuedPost)
            .filter(QueuedPost.status == PostStatus.QUEUED)
            .order_by(QueuedPost.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_approved(self) -> list[QueuedPost]:
        """Get posts approved and waiting to be posted."""
        return (
            self.db.query(QueuedPost)
            .filter(QueuedPost.status == PostStatus.APPROVED)
            .order_by(QueuedPost.created_at)
            .all()
        )

    def get_scheduled(self) -> list[QueuedPost]:
        """Get posts scheduled for specific times."""
        return (
            self.db.query(QueuedPost)
            .filter(QueuedPost.status == PostStatus.SCHEDULED)
            .order_by(QueuedPost.scheduled_time)
            .all()
        )

    def get_posted(self, limit: int = 50) -> list[QueuedPost]:
        """Get history of posted content."""
        return (
            self.db.query(QueuedPost)
            .filter(QueuedPost.status == PostStatus.POSTED)
            .order_by(QueuedPost.posted_at.desc())
            .limit(limit)
            .all()
        )

    def get_rejected(self, limit: int = 20) -> list[QueuedPost]:
        """Get rejected posts."""
        return (
            self.db.query(QueuedPost)
            .filter(QueuedPost.status == PostStatus.REJECTED)
            .order_by(QueuedPost.updated_at.desc())
            .limit(limit)
            .all()
        )

    def get_by_id(self, post_id: int) -> QueuedPost | None:
        """Get a single post by ID."""
        return self.db.query(QueuedPost).filter(QueuedPost.id == post_id).first()

    def get_stats(self) -> dict:
        """Return counts by status."""
        result = {}
        for status in PostStatus:
            count = (
                self.db.query(QueuedPost)
                .filter(QueuedPost.status == status)
                .count()
            )
            result[status.value] = count
        result["total"] = sum(result.values())
        return result

    # ── Write operations ──────────────────────────────────────

    def approve(
        self,
        post_id: int,
        edited_content: str | None = None,
        scheduled_time: datetime | None = None,
    ) -> QueuedPost | None:
        """Approve a post. Optionally edit and/or schedule it."""
        post = self.get_by_id(post_id)
        if not post or post.status not in (PostStatus.QUEUED, PostStatus.DRAFT):
            return None

        if edited_content and edited_content.strip() != post.content.strip():
            post.user_edits = edited_content.strip()
            post.content = edited_content.strip()
            post.word_count = len(edited_content.split())

        if scheduled_time:
            post.status = PostStatus.SCHEDULED
            post.scheduled_time = scheduled_time
        else:
            post.status = PostStatus.APPROVED

        post.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(post)
        return post

    def schedule(self, post_id: int, scheduled_time: datetime) -> QueuedPost | None:
        """Schedule a post for a specific time. Also works as reschedule."""
        post = self.get_by_id(post_id)
        if not post or post.status not in (
            PostStatus.QUEUED, PostStatus.DRAFT, PostStatus.APPROVED, PostStatus.SCHEDULED
        ):
            return None
        post.status = PostStatus.SCHEDULED
        post.scheduled_time = scheduled_time
        post.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(post)
        return post

    def unschedule(self, post_id: int) -> QueuedPost | None:
        """Remove scheduling from a post, reverting to approved status."""
        post = self.get_by_id(post_id)
        if not post or post.status != PostStatus.SCHEDULED:
            return None
        post.status = PostStatus.APPROVED
        post.scheduled_time = None
        post.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(post)
        return post

    def reject(self, post_id: int, reason: str = "") -> QueuedPost | None:
        """Reject a post with optional reason."""
        post = self.get_by_id(post_id)
        if not post or post.status not in (PostStatus.QUEUED, PostStatus.DRAFT):
            return None

        post.status = PostStatus.REJECTED
        post.rejection_reason = reason
        post.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(post)
        return post

    def edit_content(self, post_id: int, new_content: str) -> QueuedPost | None:
        """Edit a post's content (while keeping it in queue)."""
        post = self.get_by_id(post_id)
        if not post or post.status not in (PostStatus.QUEUED, PostStatus.DRAFT):
            return None

        post.user_edits = new_content.strip()
        post.content = new_content.strip()
        post.word_count = len(new_content.split())
        post.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(post)
        return post

    def bulk_approve(self, post_ids: list[int]) -> list[QueuedPost]:
        """Approve multiple posts at once."""
        approved = []
        for pid in post_ids:
            post = self.approve(pid)
            if post:
                approved.append(post)
        return approved

    def bulk_reject(self, post_ids: list[int], reason: str = "") -> list[QueuedPost]:
        """Reject multiple posts at once."""
        rejected = []
        for pid in post_ids:
            post = self.reject(pid, reason)
            if post:
                rejected.append(post)
        return rejected

    def delete_post(self, post_id: int) -> bool:
        """Permanently delete a post from the queue."""
        post = self.get_by_id(post_id)
        if not post:
            return False
        self.db.delete(post)
        self.db.commit()
        return True
