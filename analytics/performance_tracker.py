"""Track post performance after publishing."""

import logging
import random
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

from auth.token_manager import TokenManager
from database.models import PostPerformance, PostStatus, QueuedPost, TemplateRecord

logger = logging.getLogger(__name__)

LINKEDIN_API_BASE = "https://api.linkedin.com"


class PerformanceTracker:
    """Tracks engagement metrics on posted content and updates template weights."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # LinkedIn API engagement fetching
    # ------------------------------------------------------------------

    def _get_linkedin_headers(self, access_token: str) -> dict[str, str]:
        """Build the standard headers for LinkedIn REST API calls."""
        return {
            "Authorization": f"Bearer {access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": "202602",
        }

    def _build_post_urn(self, linkedin_post_id: str) -> str:
        """Ensure the post identifier is a full URN.

        LinkedIn post IDs stored in the database may already be a full URN
        (e.g. ``urn:li:share:12345`` or ``urn:li:ugcPost:12345``) or just
        the numeric ID.  This helper normalises the value so it can be used
        in API paths.
        """
        if linkedin_post_id.startswith("urn:"):
            return linkedin_post_id
        # Default to ugcPost URN format when only a numeric ID is stored.
        return f"urn:li:ugcPost:{linkedin_post_id}"

    async def _fetch_social_action_count(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        post_urn: str,
        action: str,
    ) -> int:
        """Fetch the count of a single social action (likes, comments, etc.).

        Uses the v2 socialActions endpoint.  Returns 0 on any error so that
        a single failed call does not break the whole batch.
        """
        encoded_urn = quote(post_urn, safe="")
        url = f"{LINKEDIN_API_BASE}/v2/socialActions/{encoded_urn}/{action}?count=0"

        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 403:
                logger.warning(
                    "403 Forbidden fetching %s for %s — storing 0",
                    action,
                    post_urn,
                )
                return 0
            resp.raise_for_status()
            data = resp.json()
            return data.get("paging", {}).get("total", 0)
        except httpx.HTTPStatusError as exc:
            logger.error(
                "HTTP %s fetching %s for %s: %s",
                exc.response.status_code,
                action,
                post_urn,
                exc,
            )
            return 0
        except Exception as exc:
            logger.error(
                "Unexpected error fetching %s for %s: %s",
                action,
                post_urn,
                exc,
            )
            return 0

    async def _fetch_social_metadata(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        post_urn: str,
    ) -> dict[str, int] | None:
        """Try the REST socialMetadata endpoint as a single-call alternative.

        Returns a dict with likes/comments/shares if successful, or *None*
        if the endpoint is unavailable so the caller can fall back to the
        individual socialActions endpoints.
        """
        encoded_urn = quote(post_urn, safe="")
        url = f"{LINKEDIN_API_BASE}/rest/socialMetadata/{encoded_urn}"

        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 403:
                logger.debug(
                    "socialMetadata endpoint returned 403 for %s — will fall back",
                    post_urn,
                )
                return None
            resp.raise_for_status()
            data = resp.json()
            return {
                "likes": data.get("totalLikes", data.get("likeCount", 0)),
                "comments": data.get("totalComments", data.get("commentCount", 0)),
                "shares": data.get("totalShares", data.get("shareCount", 0)),
            }
        except Exception:
            return None

    async def _fetch_engagement_for_post(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        post: "QueuedPost",
    ) -> dict[str, int]:
        """Fetch engagement numbers for a single *QueuedPost* row.

        Tries the REST socialMetadata endpoint first (one call).  If that is
        unavailable, falls back to individual socialActions calls.
        """
        post_urn = self._build_post_urn(post.linkedin_post_id)

        # Attempt the single-call endpoint first.
        meta = await self._fetch_social_metadata(client, headers, post_urn)
        if meta is not None:
            return meta

        # Fallback: individual calls for likes and comments.
        likes = await self._fetch_social_action_count(client, headers, post_urn, "likes")
        comments = await self._fetch_social_action_count(client, headers, post_urn, "comments")

        return {
            "likes": likes,
            "comments": comments,
            "shares": 0,  # shares not available via this endpoint
        }

    def _upsert_performance(self, post: "QueuedPost", metrics: dict[str, int]) -> PostPerformance:
        """Create or update the PostPerformance record for *post*."""
        perf = post.performance
        if perf is None:
            perf = PostPerformance(post_id=post.id)
            self.db.add(perf)

        perf.likes = metrics.get("likes", 0)
        perf.comments = metrics.get("comments", 0)
        perf.shares = metrics.get("shares", 0)
        perf.impressions = metrics.get("impressions", perf.impressions or 0)
        perf.last_checked = datetime.utcnow()
        return perf

    async def fetch_engagement_from_linkedin(self) -> int:
        """Fetch engagement data from LinkedIn for all POSTED posts.

        Returns the number of posts whose engagement was successfully updated.
        """
        token_manager = TokenManager(self.db)
        access_token = token_manager.get_valid_access_token()
        if not access_token:
            logger.error("No valid LinkedIn access token available — cannot fetch engagement")
            return 0

        headers = self._get_linkedin_headers(access_token)

        # All posted posts that have a linkedin_post_id set.
        posts = (
            self.db.query(QueuedPost)
            .filter(
                QueuedPost.status == PostStatus.POSTED,
                QueuedPost.linkedin_post_id.isnot(None),
                QueuedPost.linkedin_post_id != "",
            )
            .all()
        )

        if not posts:
            logger.info("No posted posts with a LinkedIn post ID found")
            return 0

        logger.info("Fetching engagement for %d posted posts", len(posts))

        updated = 0
        async with httpx.AsyncClient(timeout=30.0) as client:
            for post in posts:
                try:
                    metrics = await self._fetch_engagement_for_post(client, headers, post)
                    self._upsert_performance(post, metrics)
                    updated += 1
                    logger.info(
                        "Post %d (%s): likes=%d, comments=%d, shares=%d",
                        post.id,
                        post.linkedin_post_id,
                        metrics.get("likes", 0),
                        metrics.get("comments", 0),
                        metrics.get("shares", 0),
                    )
                except Exception as exc:
                    logger.error("Failed to fetch engagement for post %d: %s", post.id, exc)

        self.db.commit()
        logger.info("Updated engagement for %d / %d posts", updated, len(posts))
        return updated

    async def fetch_single_post_engagement(self, post_id: int) -> dict[str, int] | None:
        """Fetch and store engagement data for a specific post.

        Returns the engagement metrics dict on success, or ``None`` if the
        post was not found or no valid token is available.
        """
        post = (
            self.db.query(QueuedPost)
            .filter(
                QueuedPost.id == post_id,
                QueuedPost.status == PostStatus.POSTED,
            )
            .first()
        )

        if not post:
            logger.warning("Post %d not found or not in POSTED status", post_id)
            return None

        if not post.linkedin_post_id:
            logger.warning("Post %d has no linkedin_post_id", post_id)
            return None

        token_manager = TokenManager(self.db)
        access_token = token_manager.get_valid_access_token()
        if not access_token:
            logger.error("No valid LinkedIn access token — cannot fetch engagement for post %d", post_id)
            return None

        headers = self._get_linkedin_headers(access_token)

        async with httpx.AsyncClient(timeout=30.0) as client:
            metrics = await self._fetch_engagement_for_post(client, headers, post)

        self._upsert_performance(post, metrics)
        self.db.commit()

        logger.info(
            "Post %d engagement updated: likes=%d, comments=%d, shares=%d",
            post_id,
            metrics.get("likes", 0),
            metrics.get("comments", 0),
            metrics.get("shares", 0),
        )
        return metrics

    # ------------------------------------------------------------------
    # Sample / test data generation
    # ------------------------------------------------------------------

    def create_sample_performance_data(self) -> int:
        """Generate realistic sample engagement data for testing.

        Finds all POSTED posts that do **not** yet have a PostPerformance
        record and creates one with plausible random numbers.

        Returns the number of records created.
        """
        posts = (
            self.db.query(QueuedPost)
            .outerjoin(PostPerformance, PostPerformance.post_id == QueuedPost.id)
            .filter(
                QueuedPost.status == PostStatus.POSTED,
                PostPerformance.id.is_(None),
            )
            .all()
        )

        if not posts:
            logger.info("No POSTED posts without performance data found")
            return 0

        created = 0
        for post in posts:
            perf = PostPerformance(
                post_id=post.id,
                likes=random.randint(5, 150),
                comments=random.randint(0, 25),
                shares=random.randint(0, 15),
                impressions=random.randint(100, 5000),
                last_checked=datetime.utcnow(),
            )
            self.db.add(perf)
            created += 1

        self.db.commit()
        logger.info("Created sample performance data for %d posts", created)
        return created

    # ------------------------------------------------------------------
    # Template stats & reporting (original methods)
    # ------------------------------------------------------------------

    def update_template_stats(self):
        """Update template performance stats based on posted content.

        This feeds back into ContentStrategy.select_template() to weight
        high-performing templates higher.
        """
        # Get all posted posts with performance data
        posted = (
            self.db.query(QueuedPost)
            .filter(QueuedPost.status == PostStatus.POSTED)
            .filter(QueuedPost.template_name.isnot(None))
            .all()
        )

        # Group by template
        template_scores: dict[str, list[float]] = {}
        for post in posted:
            if not post.template_name:
                continue
            perf = post.performance
            if perf:
                # Simple engagement score
                score = (perf.likes or 0) + (perf.comments or 0) * 3 + (perf.shares or 0) * 5
                template_scores.setdefault(post.template_name, []).append(score)

        # Update template records
        for name, scores in template_scores.items():
            avg = sum(scores) / len(scores) if scores else 0
            record = (
                self.db.query(TemplateRecord)
                .filter(TemplateRecord.name == name)
                .first()
            )
            if record:
                record.avg_performance = avg
                record.times_used = len(scores)
            else:
                record = TemplateRecord(
                    name=name,
                    avg_performance=avg,
                    times_used=len(scores),
                )
                self.db.add(record)

        self.db.commit()
        logger.info("Updated stats for %d templates", len(template_scores))

    def get_summary(self, days: int = 7) -> dict:
        """Get performance summary for recent posts."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        posts = (
            self.db.query(QueuedPost)
            .filter(
                QueuedPost.status == PostStatus.POSTED,
                QueuedPost.posted_at >= cutoff,
            )
            .all()
        )

        total_likes = 0
        total_comments = 0
        total_shares = 0
        total_impressions = 0

        for post in posts:
            if post.performance:
                total_likes += post.performance.likes or 0
                total_comments += post.performance.comments or 0
                total_shares += post.performance.shares or 0
                total_impressions += post.performance.impressions or 0

        return {
            "period_days": days,
            "posts_count": len(posts),
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_shares": total_shares,
            "total_impressions": total_impressions,
            "avg_likes": total_likes / len(posts) if posts else 0,
            "avg_comments": total_comments / len(posts) if posts else 0,
        }
