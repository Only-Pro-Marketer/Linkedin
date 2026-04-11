"""High-level LinkedIn posting logic with error handling."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from auth.token_manager import TokenManager
from config import settings
from content.post_formatter import format_for_linkedin, validate_post_content, MAX_TOTAL_NEWLINES
from database.models import ContentCalendar, PostStatus, QueuedPost
from linkedin.api_client import LinkedInAPIClient
from linkedin.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Shared rate limiter instance
rate_limiter = RateLimiter(daily_limit=80)


class LinkedInPoster:
    """Posts content to LinkedIn with token management and error handling."""

    def __init__(self, db: Session):
        self.db = db
        self.token_manager = TokenManager(db)

    async def post(self, queued_post: QueuedPost) -> bool:
        """Post a queued post to LinkedIn.

        Pipeline:
        1. Format content for LinkedIn (normalize line endings, cap newlines)
        2. Pre-post validation (block if content will be truncated)
        3. Send to LinkedIn API
        4. Post-publish verification (fetch back and compare)

        Updates the post status to POSTED on success or FAILED on error.
        Returns True if the post was published successfully.
        """
        # Check rate limit
        if not rate_limiter.can_post():
            logger.warning("Rate limit reached, skipping post %s", queued_post.id)
            return False

        # Get valid access token
        access_token = self.token_manager.get_valid_access_token()
        if not access_token:
            logger.error("No valid access token — cannot post")
            queued_post.status = PostStatus.FAILED
            queued_post.rejection_reason = "No valid access token"
            self.db.commit()
            return False

        # Get person URN
        person_urn = self.token_manager.get_person_urn()
        if not person_urn:
            logger.error("No person URN stored — need to re-authenticate")
            queued_post.status = PostStatus.FAILED
            queued_post.rejection_reason = "No person URN"
            self.db.commit()
            return False

        # ── Step 1: Format content ──
        # Re-run formatter to ensure blank-line limits are enforced even for
        # content that was saved before the formatter was updated.
        raw_content = queued_post.user_edits or queued_post.content
        logger.info(
            "Post %s raw content: source=%s, chars=%d, newlines=%d, first_80=%r",
            queued_post.id,
            "user_edits" if queued_post.user_edits else "content",
            len(raw_content),
            raw_content.count("\n"),
            raw_content[:80],
        )
        content = format_for_linkedin(raw_content, queued_post.topic or "")

        # Safety net: if content STILL exceeds newline limit after formatting,
        # do a simple line trim instead of re-running the full formatter
        # (re-running would re-apply regex/spacing on already-formatted content)
        newline_count = content.count("\n")
        if newline_count > MAX_TOTAL_NEWLINES:
            logger.warning(
                "Post %s still has %d newlines after formatting — trimming excess lines",
                queued_post.id, newline_count,
            )
            lines = content.split("\n")
            content = "\n".join(lines[:MAX_TOTAL_NEWLINES + 1]).strip()

        # ── Step 2: Pre-post validation ──
        validation = validate_post_content(content)
        logger.info(
            "Pre-post validation post_id=%s: valid=%s, chars=%d, bytes=%d, "
            "newlines=%d, blank_lines=%d, hash=%s",
            queued_post.id,
            validation["valid"],
            validation["stats"]["char_count"],
            validation["stats"]["byte_count"],
            validation["stats"]["total_newlines"],
            validation["stats"]["blank_lines"],
            validation["content_hash"][:16],
        )

        if not validation["valid"]:
            issues_str = "; ".join(validation["issues"])
            logger.error(
                "BLOCKED post %s — pre-post validation failed: %s",
                queued_post.id,
                issues_str,
            )
            queued_post.status = PostStatus.FAILED
            queued_post.rejection_reason = f"Content validation failed: {issues_str}"
            self.db.commit()
            return False

        if validation["warnings"]:
            logger.warning(
                "Post %s has warnings: %s",
                queued_post.id,
                "; ".join(validation["warnings"]),
            )

        logger.info(
            "Post %s content_source=%s, has_image=%s, first_100=%r, last_100=%r",
            queued_post.id,
            "user_edits" if queued_post.user_edits else "content",
            queued_post.has_image,
            validation["first_100"],
            validation["last_100"],
        )

        # ── Step 3: Send to LinkedIn API ──
        queued_post.status = PostStatus.POSTING
        self.db.commit()

        client = LinkedInAPIClient(access_token)
        if queued_post.has_video and queued_post.video_path:
            result = await client.create_video_post(person_urn, content, queued_post.video_path)
        elif queued_post.has_image and queued_post.image_path:
            result = await client.create_image_post(person_urn, content, queued_post.image_path)
        else:
            result = await client.create_text_post(person_urn, content)
        rate_limiter.record_call()

        if not result["success"]:
            queued_post.status = PostStatus.FAILED
            queued_post.rejection_reason = f"API error: {result.get('error', 'unknown')}"
            self.db.commit()
            logger.error("Failed to post %s: %s", queued_post.id, result.get("error"))
            return False

        queued_post.status = PostStatus.POSTED
        queued_post.posted_at = datetime.utcnow()
        queued_post.linkedin_post_id = result.get("post_urn", "")
        self.db.commit()
        logger.info(
            "Posted successfully: post_id=%s, urn=%s, chars_sent=%d",
            queued_post.id,
            result.get("post_urn"),
            len(content),
        )

        # ── Step 4: Post-publish verification ──
        post_urn = result.get("post_urn", "")
        if post_urn:
            await self._verify_published_content(
                client, queued_post.id, post_urn, content
            )

        return True

    async def _verify_published_content(
        self,
        client: LinkedInAPIClient,
        post_id: int,
        post_urn: str,
        sent_content: str,
    ) -> None:
        """Fetch the published post from LinkedIn and verify content integrity.

        Logs a CRITICAL warning if the content on LinkedIn doesn't match what
        was sent — this catches silent truncation by the LinkedIn API.
        Also stores verification result in rejection_reason for dashboard visibility.
        """
        try:
            published = await client.get_post(post_urn)
            if not published:
                logger.warning(
                    "Post %s: could not fetch published post for verification (urn=%s)",
                    post_id,
                    post_urn,
                )
                return

            published_text = published.get("commentary", "")
            sent_len = len(sent_content)
            published_len = len(published_text)
            sent_newlines = sent_content.count("\n")
            published_newlines = published_text.count("\n") if published_text else 0

            if published_len < sent_len * 0.9:
                # Content was truncated by LinkedIn!
                loss_pct = (1 - published_len / sent_len) * 100
                truncation_msg = (
                    f"TRUNCATED by LinkedIn: sent {sent_len} chars "
                    f"({sent_newlines} newlines) but LinkedIn stored only "
                    f"{published_len} chars ({published_newlines} newlines) — "
                    f"{loss_pct:.0f}% lost. "
                    f"LinkedIn ends at: {published_text[-80:]!r}"
                )
                logger.critical(
                    "CONTENT TRUNCATION DETECTED — post_id=%s: %s",
                    post_id,
                    truncation_msg,
                )
                # Store in DB so it's visible in the dashboard
                post = self.db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
                if post:
                    post.rejection_reason = truncation_msg
                    self.db.commit()
            elif published_len == sent_len:
                logger.info(
                    "Post %s verification OK: %d chars, %d newlines confirmed on LinkedIn",
                    post_id,
                    published_len,
                    published_newlines,
                )
            else:
                # Minor difference (LinkedIn may normalize whitespace)
                logger.info(
                    "Post %s verification: sent %d chars (%d newlines), "
                    "LinkedIn has %d chars (%d newlines) "
                    "(minor difference, likely whitespace normalization)",
                    post_id,
                    sent_len,
                    sent_newlines,
                    published_len,
                    published_newlines,
                )
        except Exception as e:
            logger.warning(
                "Post %s: verification failed (non-critical): %s",
                post_id,
                e,
            )

    async def post_immediately(self, post_id: int) -> bool:
        """Find a post by ID and post it immediately."""
        post = self.db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
        if not post:
            logger.error("Post %s not found", post_id)
            return False
        if post.status not in (
            PostStatus.QUEUED,
            PostStatus.APPROVED,
            PostStatus.SCHEDULED,
        ):
            logger.error("Post %s has status %s — cannot post", post_id, post.status)
            return False
        return await self.post(post)

    async def post_due_scheduled(self) -> list[int]:
        """Find and post all SCHEDULED posts whose time has arrived.

        Returns list of post IDs that were successfully posted.
        """
        now = datetime.utcnow()
        due_posts = (
            self.db.query(QueuedPost)
            .filter(
                QueuedPost.status == PostStatus.SCHEDULED,
                QueuedPost.scheduled_time <= now,
            )
            .order_by(QueuedPost.scheduled_time)
            .all()
        )

        posted_ids = []
        for post in due_posts:
            if not rate_limiter.can_post():
                logger.warning("Rate limit reached, stopping scheduled posts")
                break
            if await self.post(post):
                posted_ids.append(post.id)

        return posted_ids

    def _is_optimal_posting_window(self) -> bool:
        """Check if current time falls within a ContentCalendar slot (+/- 15 min).

        Uses the configured timezone (default: America/Toronto).
        Returns True if now is within any active slot window.
        """
        try:
            tz = ZoneInfo(settings.POSTING_TIMEZONE)
        except (KeyError, Exception):
            tz = ZoneInfo("America/Toronto")

        now = datetime.now(tz)
        current_day = now.weekday()  # 0=Monday

        active_slots = (
            self.db.query(ContentCalendar)
            .filter(
                ContentCalendar.is_active == True,
                ContentCalendar.day_of_week == current_day,
            )
            .all()
        )

        for slot in active_slots:
            try:
                slot_hour, slot_minute = map(int, slot.time_slot.split(":"))
                slot_time = now.replace(hour=slot_hour, minute=slot_minute, second=0, microsecond=0)
                diff_minutes = abs((now - slot_time).total_seconds()) / 60
                if diff_minutes <= 15:
                    return True
            except (ValueError, AttributeError):
                continue

        return False

    async def post_next_approved(self) -> int | None:
        """Post the oldest APPROVED post during optimal time windows.

        Only posts if current time is within a ContentCalendar slot (+/- 15 min),
        unless the approved queue has 5+ posts backed up (safety valve).
        Returns the post ID or None.
        """
        approved_count = (
            self.db.query(QueuedPost)
            .filter(QueuedPost.status == PostStatus.APPROVED)
            .count()
        )

        if approved_count == 0:
            return None

        # Only post during optimal windows (unless queue is dangerously backed up)
        if not self._is_optimal_posting_window() and approved_count < 5:
            logger.debug(
                "Not in optimal posting window and only %d approved posts — skipping",
                approved_count,
            )
            return None

        post = (
            self.db.query(QueuedPost)
            .filter(QueuedPost.status == PostStatus.APPROVED)
            .order_by(QueuedPost.created_at)
            .first()
        )
        if not post:
            return None
        if await self.post(post):
            return post.id
        return None
