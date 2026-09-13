"""High-level LinkedIn posting logic with safety gates and error handling.

Safety rules enforced here (for every publish path):
- Only APPROVED or SCHEDULED posts are ever published.
- At most POSTS_PER_DAY publishes per local day.
- Automatic publishes keep MIN_HOURS_BETWEEN_POSTS between them.
- A post interrupted mid-publish is marked FAILED on restart, never retried
  automatically (it may already be live on LinkedIn).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from auth.token_manager import TokenManager
from config import settings
from content.post_formatter import MAX_TOTAL_NEWLINES, format_for_linkedin, validate_post_content
from database.models import ContentCalendar, PostStatus, QueuedPost
from linkedin.api_client import LinkedInAPIClient
from utils.timeutil import local_day_bounds_utc, local_now

logger = logging.getLogger(__name__)

STALE_POSTING_MINUTES = 10
SLOT_WINDOW_MINUTES = 15

PUBLISHABLE = (PostStatus.APPROVED, PostStatus.SCHEDULED)


@dataclass
class PublishResult:
    ok: bool
    code: str = "ok"  # ok, not_found, bad_status, limit, auth, invalid, api_error
    message: str = ""
    post_urn: str = ""

    @property
    def http_status(self) -> int:
        return {
            "ok": 200, "not_found": 404, "bad_status": 409, "limit": 429,
            "auth": 401, "invalid": 422, "api_error": 502,
        }.get(self.code, 500)


class LinkedInPoster:
    """Posts content to LinkedIn with token management and error handling."""

    def __init__(self, db: Session):
        self.db = db
        self.token_manager = TokenManager(db)

    # ── Safety gates ──────────────────────────────────────────

    def posted_today_count(self) -> int:
        start, end = local_day_bounds_utc()
        return (
            self.db.query(QueuedPost)
            .filter(
                QueuedPost.status == PostStatus.POSTED,
                QueuedPost.posted_at >= start,
                QueuedPost.posted_at < end,
            )
            .count()
        )

    def last_posted_at(self) -> datetime | None:
        return (
            self.db.query(func.max(QueuedPost.posted_at))
            .filter(QueuedPost.status == PostStatus.POSTED)
            .scalar()
        )

    def check_limits(self, *, enforce_gap: bool) -> PublishResult | None:
        """Return a blocking PublishResult, or None when publishing is allowed."""
        if self.posted_today_count() >= settings.POSTS_PER_DAY:
            return PublishResult(
                False, "limit",
                f"Daily limit reached ({settings.POSTS_PER_DAY} per day). "
                "It resets at midnight, or raise it in Settings.",
            )
        if enforce_gap and settings.MIN_HOURS_BETWEEN_POSTS > 0:
            last = self.last_posted_at()
            if last and datetime.utcnow() - last < timedelta(hours=settings.MIN_HOURS_BETWEEN_POSTS):
                return PublishResult(
                    False, "limit",
                    f"Waiting {settings.MIN_HOURS_BETWEEN_POSTS:g}h between posts.",
                )
        return None

    def _fail(self, post: QueuedPost, message: str) -> None:
        post.status = PostStatus.FAILED
        post.last_error = message[:2000]
        self.db.commit()

    # ── Publishing ────────────────────────────────────────────

    async def publish(self, queued_post: QueuedPost, *, enforce_gap: bool = True) -> PublishResult:
        """Publish one post. Pipeline: gates → format → validate → send → verify."""
        if queued_post.status not in PUBLISHABLE:
            return PublishResult(False, "bad_status", "Approve this post before publishing it.")

        blocked = self.check_limits(enforce_gap=enforce_gap)
        if blocked:
            logger.info("Post %s not published: %s", queued_post.id, blocked.message)
            return blocked

        access_token = self.token_manager.get_valid_access_token()
        person_urn = self.token_manager.get_person_urn()
        if not access_token or not person_urn:
            msg = "LinkedIn is not connected. Reconnect in Settings, then retry."
            self._fail(queued_post, msg)
            return PublishResult(False, "auth", msg)

        # ── Step 1: Format content ──
        raw_content = queued_post.user_edits or queued_post.content
        content = format_for_linkedin(raw_content, queued_post.topic or "")
        if content.count("\n") > MAX_TOTAL_NEWLINES:
            content = "\n".join(content.split("\n")[: MAX_TOTAL_NEWLINES + 1]).strip()

        # ── Step 2: Pre-post validation ──
        validation = validate_post_content(content)
        if not validation["valid"]:
            msg = "Content check failed: " + "; ".join(validation["issues"])
            self._fail(queued_post, msg)
            return PublishResult(False, "invalid", msg)
        if validation["warnings"]:
            logger.warning("Post %s warnings: %s", queued_post.id, "; ".join(validation["warnings"]))

        # ── Step 3: Send to LinkedIn API ──
        queued_post.status = PostStatus.POSTING
        queued_post.attempt_count = (queued_post.attempt_count or 0) + 1
        self.db.commit()

        client = LinkedInAPIClient(access_token)
        try:
            if queued_post.has_video and queued_post.video_path:
                result = await client.create_video_post(person_urn, content, queued_post.video_path)
            elif queued_post.has_image and queued_post.image_path:
                result = await client.create_image_post(person_urn, content, queued_post.image_path)
            else:
                result = await client.create_text_post(person_urn, content)
        except Exception as e:  # network error: the post may or may not be live
            msg = f"Network error while publishing ({e}). Check LinkedIn before retrying."
            self._fail(queued_post, msg)
            return PublishResult(False, "api_error", msg)

        if not result.get("success"):
            status = result.get("status_code", "")
            msg = f"LinkedIn API error {status}: {str(result.get('error', 'unknown'))[:300]}"
            self._fail(queued_post, msg)
            return PublishResult(False, "api_error", msg)

        post_urn = result.get("post_urn", "")
        queued_post.status = PostStatus.POSTED
        queued_post.posted_at = datetime.utcnow()
        queued_post.linkedin_post_id = post_urn
        queued_post.last_error = (
            "Media upload failed, so this was posted as text only." if result.get("media_fallback") else None
        )
        self.db.commit()
        logger.info("Posted post_id=%s urn=%s chars=%d", queued_post.id, post_urn, len(content))

        if queued_post.first_comment and post_urn:  # links go in the first comment
            try:
                from engagement.publisher import queue_first_comment
                queue_first_comment(self.db, queued_post)
            except Exception:
                logger.exception("Couldn't schedule the first comment for post %s", queued_post.id)

        # ── Step 4: Post-publish verification ──
        if post_urn:
            await self._verify_published_content(client, queued_post, post_urn, content)

        return PublishResult(True, "ok", "Published to LinkedIn.", post_urn)

    async def post(self, queued_post: QueuedPost) -> bool:
        """Backward-compatible wrapper returning only success."""
        return (await self.publish(queued_post)).ok

    async def _verify_published_content(
        self, client: LinkedInAPIClient, post: QueuedPost, post_urn: str, sent_content: str
    ) -> None:
        """Fetch the post back; record a warning if LinkedIn truncated it."""
        try:
            published = await client.get_post(post_urn)
            if not published:
                return
            published_text = published.get("commentary", "")
            sent_len, published_len = len(sent_content), len(published_text)
            if sent_len and published_len < sent_len * 0.9:
                loss = (1 - published_len / sent_len) * 100
                msg = (
                    f"LinkedIn truncated this post: sent {sent_len} chars but it stored "
                    f"{published_len} ({loss:.0f}% lost)."
                )
                logger.critical("CONTENT TRUNCATION post_id=%s: %s", post.id, msg)
                post.last_error = msg
                self.db.commit()
        except Exception as e:
            logger.warning("Post %s: verification failed (non-critical): %s", post.id, e)

    async def post_immediately(self, post_id: int) -> PublishResult:
        """Publish an approved or scheduled post now (user clicked Post Now)."""
        post = self.db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
        if not post:
            return PublishResult(False, "not_found", "Post not found.")
        return await self.publish(post, enforce_gap=False)

    async def post_due_scheduled(self) -> list[int]:
        """Publish SCHEDULED posts whose (UTC) time has arrived."""
        due_posts = (
            self.db.query(QueuedPost)
            .filter(
                QueuedPost.status == PostStatus.SCHEDULED,
                QueuedPost.scheduled_time <= datetime.utcnow(),
            )
            .order_by(QueuedPost.scheduled_time)
            .all()
        )
        posted_ids = []
        for post in due_posts:
            result = await self.publish(post, enforce_gap=False)
            if result.ok:
                posted_ids.append(post.id)
            elif result.code == "limit":
                break
        return posted_ids

    def _is_optimal_posting_window(self) -> bool:
        """True if now (local time) is within ±15 min of an active calendar slot."""
        now = local_now()
        slots = (
            self.db.query(ContentCalendar)
            .filter(ContentCalendar.is_active == True, ContentCalendar.day_of_week == now.weekday())  # noqa: E712
            .all()
        )
        for slot in slots:
            try:
                hour, minute = map(int, slot.time_slot.split(":"))
            except (ValueError, AttributeError):
                continue
            slot_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if abs((now - slot_time).total_seconds()) / 60 <= SLOT_WINDOW_MINUTES:
                return True
        return False

    async def post_next_approved(self) -> int | None:
        """Publish the oldest APPROVED post, only inside a calendar slot."""
        if not self._is_optimal_posting_window():
            return None
        post = (
            self.db.query(QueuedPost)
            .filter(QueuedPost.status == PostStatus.APPROVED)
            .order_by(QueuedPost.approved_at.is_(None), QueuedPost.approved_at, QueuedPost.created_at)
            .first()
        )
        if not post:
            return None
        result = await self.publish(post, enforce_gap=True)
        return post.id if result.ok else None


def recover_stale_posts(db: Session) -> int:
    """Mark posts stuck in POSTING (app crashed mid-publish) as FAILED."""
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_POSTING_MINUTES)
    stale = (
        db.query(QueuedPost)
        .filter(QueuedPost.status == PostStatus.POSTING, QueuedPost.updated_at < cutoff)
        .all()
    )
    for post in stale:
        post.status = PostStatus.FAILED
        post.last_error = "Publishing was interrupted. Check LinkedIn before retrying — it may already be live."
    if stale:
        db.commit()
        logger.warning("Marked %d interrupted post(s) as FAILED", len(stale))
    return len(stale)
