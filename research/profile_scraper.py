"""Scrape the user's own LinkedIn profile and posts via Apify."""

import logging
import re
from datetime import datetime

from apify_client import ApifyClient
from sqlalchemy.orm import Session

from config import settings, get_anthropic_client
from database.models import MyLinkedInPost

logger = logging.getLogger(__name__)

PROFILE_ACTOR = "dev_fusion/linkedin-profile-scraper"
POSTS_ACTOR = "harvestapi/linkedin-profile-posts"


def _extract_username(linkedin_url: str) -> str | None:
    """Extract username from a LinkedIn profile URL."""
    if not linkedin_url:
        return None
    patterns = [
        r"linkedin\.com/in/([^/?#]+)",
        r"linkedin\.com/pub/([^/?#]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, linkedin_url)
        if match:
            return match.group(1).strip("/")
    if "/" not in linkedin_url and "." not in linkedin_url:
        return linkedin_url
    return None


class ProfileScraper:
    """Scrapes the user's own LinkedIn profile and posts for analytics."""

    def __init__(self, db: Session):
        self.db = db
        self.apify = ApifyClient(settings.APIFY_TOKEN)
        self.claude = get_anthropic_client()

    def scrape_my_profile(self, profile_url: str | None = None) -> dict:
        """Run a full scrape of the user's LinkedIn profile and posts.

        Returns a summary dict with profile info, new/updated post counts.
        """
        url = profile_url or settings.LINKEDIN_PROFILE_URL
        if not url:
            return {"error": "No LinkedIn profile URL configured. Set it in Settings."}

        username = _extract_username(url)
        if not username:
            return {"error": f"Could not extract username from: {url}"}

        full_url = f"https://www.linkedin.com/in/{username}"
        result = {
            "profile_url": full_url,
            "username": username,
            "profile": {},
            "new_posts": 0,
            "updated_posts": 0,
            "total_posts": 0,
            "analyzed": 0,
        }

        # 1. Fetch profile data
        profile_data = self._fetch_profile(full_url)
        if profile_data:
            result["profile"] = profile_data

        # 2. Fetch posts
        new, updated = self._fetch_posts(full_url)
        result["new_posts"] = new
        result["updated_posts"] = updated

        # 3. Get total count
        result["total_posts"] = self.db.query(MyLinkedInPost).count()

        # 4. AI-analyze un-analyzed posts
        analyzed = self._analyze_unanalyzed()
        result["analyzed"] = analyzed

        logger.info(
            "Profile scrape complete: %d new, %d updated, %d analyzed",
            new, updated, analyzed,
        )
        return result

    def _fetch_profile(self, profile_url: str) -> dict:
        """Fetch profile info via Apify."""
        try:
            run = self.apify.actor(PROFILE_ACTOR).call(
                run_input={"profileUrls": [profile_url]},
                timeout_secs=120,
            )
            dataset = self.apify.dataset(run["defaultDatasetId"])
            items = list(dataset.iterate_items())

            if not items:
                logger.warning("No profile data returned for %s", profile_url)
                return {}

            p = items[0]
            return {
                "name": p.get("fullName", ""),
                "headline": p.get("headline", ""),
                "followers": p.get("followers", 0),
                "profile_picture": p.get("profilePicHighQuality") or p.get("profilePic", ""),
                "connections": p.get("connections", 0),
            }
        except Exception as e:
            logger.warning("Profile fetch error: %s", e)
            return {}

    def _fetch_posts(self, profile_url: str) -> tuple[int, int]:
        """Fetch posts via Apify and store/update them."""
        try:
            run = self.apify.actor(POSTS_ACTOR).call(
                run_input={
                    "targetUrls": [profile_url],
                    "maxPosts": 50,
                    "scrapeReactions": False,
                    "scrapeComments": False,
                },
                timeout_secs=240,
            )
            dataset = self.apify.dataset(run["defaultDatasetId"])
            items = list(dataset.iterate_items())

            if not items:
                logger.warning("No posts returned for %s", profile_url)
                return 0, 0

            new_count = 0
            updated_count = 0

            for raw in items:
                is_new = self._store_post(raw)
                if is_new is True:
                    new_count += 1
                elif is_new is False:
                    updated_count += 1

            self.db.commit()
            return new_count, updated_count

        except Exception as e:
            logger.warning("Posts fetch error: %s", e)
            return 0, 0

    def _store_post(self, raw: dict) -> bool | None:
        """Parse and store a post. Returns True=new, False=updated, None=skipped."""
        content = raw.get("content") or ""
        if not content or len(content.strip()) < 20:
            return None

        post_url = raw.get("linkedinUrl") or ""
        post_id = raw.get("id") or raw.get("entityId") or ""

        # Parse engagement
        engagement = raw.get("engagement", {})
        likes = engagement.get("likes", 0) or 0
        comments = engagement.get("comments", 0) or 0
        shares = engagement.get("shares", 0) or 0

        # Parse date
        post_date = None
        posted_at = raw.get("postedAt")
        if isinstance(posted_at, dict):
            ts = posted_at.get("timestamp")
            if ts:
                try:
                    post_date = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts)
                except (ValueError, TypeError):
                    pass
            if not post_date:
                date_str = posted_at.get("date")
                if date_str:
                    try:
                        post_date = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass

        # Media
        images = raw.get("postImages") or []
        has_image = bool(images)
        image_url = ""
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                image_url = first.get("url", "")
            elif isinstance(first, str):
                image_url = first
        has_video = raw.get("type") == "video"

        # Check for existing post (dedup)
        if post_id:
            existing = (
                self.db.query(MyLinkedInPost)
                .filter(MyLinkedInPost.linkedin_post_id == str(post_id))
                .first()
            )
            if existing:
                existing.likes = likes
                existing.comments = comments
                existing.shares = shares
                existing.updated_at = datetime.utcnow()
                return False

        post = MyLinkedInPost(
            content=content.strip(),
            post_url=post_url,
            linkedin_post_id=str(post_id) if post_id else None,
            post_date=post_date,
            likes=likes,
            comments=comments,
            shares=shares,
            has_image=has_image,
            has_video=has_video,
            image_url=image_url or None,
        )
        self.db.add(post)
        return True

    def _analyze_unanalyzed(self) -> int:
        """Run Claude AI analysis on un-analyzed posts."""
        unanalyzed = (
            self.db.query(MyLinkedInPost)
            .filter(MyLinkedInPost.ai_analyzed.is_(False))
            .limit(10)
            .all()
        )

        analyzed = 0
        for post in unanalyzed:
            try:
                self._analyze_post(post)
                analyzed += 1
            except Exception as e:
                logger.warning("Failed to analyze my post %s: %s", post.id, e)

        if analyzed:
            self.db.commit()
        return analyzed

    def _analyze_post(self, post: MyLinkedInPost):
        """Analyze a single post with Claude."""
        prompt = f"""Analyze this LinkedIn post and provide a structured breakdown.

POST CONTENT:
---
{post.content}
---

ENGAGEMENT: {post.likes} likes, {post.comments} comments, {post.shares} shares

Respond in EXACTLY this format:

HOOK_STYLE: [one of: bold_statement, question, story, statistic, contrarian, listicle, personal, how_to, curiosity_gap, challenge]
CONTENT_FORMAT: [one of: list, story, framework, tips, case_study, opinion, educational, motivational, behind_the_scenes, comparison]
TOPIC: [main topic in 3-5 words]
KEY_TAKEAWAY: [the core insight, 1-2 sentences]
WHY_IT_WORKS: [why this post performed well or poorly — specific analysis, 2-3 sentences]"""

        try:
            message = self.claude.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=600,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            result = message.content[0].text.strip()

            fields = {}
            for line in result.split("\n"):
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip().lower().replace(" ", "_")
                    fields[key] = value.strip()

            post.hook_style = fields.get("hook_style", "")[:100]
            post.content_format = fields.get("content_format", "")[:100]
            post.topic = fields.get("topic", "")[:200]
            post.key_takeaway = fields.get("key_takeaway", "")
            post.why_it_works = fields.get("why_it_works", "")
            post.ai_analyzed = True

        except Exception as e:
            logger.error("Claude analysis error for post %s: %s", post.id, e)

    def get_profile_stats(self) -> dict:
        """Return aggregate stats for the user's own posts."""
        posts = self.db.query(MyLinkedInPost).all()
        if not posts:
            return {
                "total_posts": 0,
                "total_likes": 0,
                "total_comments": 0,
                "total_shares": 0,
                "avg_likes": 0,
                "avg_comments": 0,
                "avg_shares": 0,
                "top_post": None,
                "posting_frequency": None,
            }

        total_likes = sum(p.likes for p in posts)
        total_comments = sum(p.comments for p in posts)
        total_shares = sum(p.shares for p in posts)
        count = len(posts)

        # Top performing post
        best = max(posts, key=lambda p: p.likes + p.comments * 3 + p.shares * 5)
        top_post = {
            "id": best.id,
            "content": best.content[:200] + "..." if len(best.content) > 200 else best.content,
            "likes": best.likes,
            "comments": best.comments,
            "shares": best.shares,
            "post_url": best.post_url,
            "post_date": best.post_date.isoformat() if best.post_date else None,
        }

        # Posting frequency
        dated = sorted([p for p in posts if p.post_date], key=lambda p: p.post_date)
        frequency = None
        if len(dated) >= 2:
            span = (dated[-1].post_date - dated[0].post_date).days
            if span > 0:
                posts_per_week = round(len(dated) / (span / 7), 1)
                frequency = f"{posts_per_week}x/week"

        return {
            "total_posts": count,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_shares": total_shares,
            "avg_likes": round(total_likes / count, 1),
            "avg_comments": round(total_comments / count, 1),
            "avg_shares": round(total_shares / count, 1),
            "top_post": top_post,
            "posting_frequency": frequency,
        }
