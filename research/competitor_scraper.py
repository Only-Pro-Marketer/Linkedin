"""LinkedIn competitor scraper — fetches profiles and posts via Apify actors."""

import logging
import re
from datetime import datetime

import anthropic
from apify_client import ApifyClient
from sqlalchemy.orm import Session

from config import settings, get_anthropic_client
from database.models import Competitor, CompetitorPost

logger = logging.getLogger(__name__)

# Apify actor IDs
PROFILE_ACTOR = "dev_fusion/linkedin-profile-scraper"
POSTS_ACTOR = "harvestapi/linkedin-profile-posts"


def _extract_username(linkedin_url: str) -> str | None:
    """Extract the username from a LinkedIn profile URL."""
    if not linkedin_url:
        return None
    # Handle various LinkedIn URL formats
    patterns = [
        r"linkedin\.com/in/([^/?#]+)",
        r"linkedin\.com/pub/([^/?#]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, linkedin_url)
        if match:
            return match.group(1).strip("/")
    # Maybe they just typed the username directly
    if "/" not in linkedin_url and "." not in linkedin_url:
        return linkedin_url
    return None


def _build_profile_url(username: str) -> str:
    """Build a full LinkedIn profile URL from a username."""
    return f"https://www.linkedin.com/in/{username}"


class CompetitorScraper:
    """Scrapes LinkedIn profiles and posts for tracked competitors."""

    def __init__(self, db: Session):
        self.db = db
        self.apify = ApifyClient(settings.APIFY_TOKEN)
        self.claude = get_anthropic_client()

    def scrape_all_competitors(self) -> dict:
        """Run a full scrape cycle for all active competitors."""
        competitors = (
            self.db.query(Competitor)
            .filter(Competitor.is_active.is_(True))
            .all()
        )

        results = {"scraped": 0, "new_posts": 0, "analyzed": 0, "errors": []}

        for comp in competitors:
            try:
                new_posts = self.scrape_competitor(comp)
                results["scraped"] += 1
                results["new_posts"] += new_posts

                # AI-analyze any un-analyzed posts
                analyzed = self._analyze_unanalyzed_posts(comp)
                results["analyzed"] += analyzed

            except Exception as e:
                logger.error("Failed to scrape %s: %s", comp.name, e)
                comp.scrape_status = "failed"
                comp.scrape_error = str(e)
                self.db.commit()
                results["errors"].append({"competitor": comp.name, "error": str(e)})

        logger.info(
            "Scrape cycle complete: %d scraped, %d new posts, %d analyzed, %d errors",
            results["scraped"], results["new_posts"], results["analyzed"], len(results["errors"]),
        )
        return results

    def scrape_competitor(self, comp: Competitor) -> int:
        """Scrape a single competitor's profile and recent posts."""
        username = comp.linkedin_username or _extract_username(comp.linkedin_url or "")
        if not username:
            raise ValueError(f"No LinkedIn username found for {comp.name}")

        # Save the extracted username for future use
        if not comp.linkedin_username:
            comp.linkedin_username = username

        profile_url = _build_profile_url(username)

        # First-time scrape gets 100 posts, daily updates get 20
        is_first_scrape = comp.last_scraped_at is None
        max_posts = 100 if is_first_scrape else 20

        # 1. Fetch profile data
        self._fetch_profile(comp, profile_url)

        # 2. Fetch posts
        new_count = self._fetch_posts(comp, profile_url, max_posts=max_posts)

        # 3. Update stats
        self._recalculate_stats(comp)

        comp.last_scraped_at = datetime.utcnow()
        comp.scrape_status = "success"
        comp.scrape_error = None
        self.db.commit()

        logger.info(
            "%s scrape for %s: %d new posts (max_posts=%d)",
            "Initial" if is_first_scrape else "Update", comp.name, new_count, max_posts,
        )
        return new_count

    def _fetch_profile(self, comp: Competitor, profile_url: str):
        """Fetch the competitor's LinkedIn profile info via Apify."""
        try:
            run = self.apify.actor(PROFILE_ACTOR).call(
                run_input={"profileUrls": [profile_url]},
                timeout_secs=120,
            )

            dataset = self.apify.dataset(run["defaultDatasetId"])
            items = list(dataset.iterate_items())

            if not items:
                logger.warning("No profile data returned for %s", profile_url)
                return

            profile = items[0]

            # Update profile fields from Apify response
            comp.profile_picture = (
                profile.get("profilePicHighQuality")
                or profile.get("profilePic")
                or comp.profile_picture
            )
            comp.headline = profile.get("headline") or comp.headline
            comp.follower_count = profile.get("followers") or comp.follower_count

            # Update name if we got a better one
            full_name = profile.get("fullName")
            if full_name and full_name != comp.linkedin_username:
                comp.name = full_name

            logger.info("Updated profile for %s: %s followers", comp.name, comp.follower_count)

        except Exception as e:
            logger.warning("Profile fetch error for %s: %s", profile_url, e)

    def _fetch_posts(self, comp: Competitor, profile_url: str, max_posts: int = 20) -> int:
        """Fetch recent posts via Apify and store new ones."""
        try:
            run = self.apify.actor(POSTS_ACTOR).call(
                run_input={
                    "targetUrls": [profile_url],
                    "maxPosts": max_posts,
                    "scrapeReactions": False,
                    "scrapeComments": False,
                },
                timeout_secs=300 if max_posts > 50 else 180,
            )

            dataset = self.apify.dataset(run["defaultDatasetId"])
            items = list(dataset.iterate_items())

            if not items:
                logger.warning("No posts returned for %s", profile_url)
                return 0

            new_count = 0
            for raw_post in items:
                if self._store_post(comp, raw_post):
                    new_count += 1

            self.db.commit()
            logger.info("Fetched %d new posts for %s", new_count, comp.name)
            return new_count

        except Exception as e:
            logger.warning("Posts fetch error for %s: %s", profile_url, e)
            return 0

    def _store_post(self, comp: Competitor, raw: dict) -> bool:
        """Parse a raw Apify post and store it if it's new."""
        content = raw.get("content") or ""
        if not content or len(content.strip()) < 20:
            return False

        # Dedup by post ID
        post_url = raw.get("linkedinUrl") or ""
        post_id = raw.get("id") or raw.get("entityId") or ""

        if post_id:
            existing = (
                self.db.query(CompetitorPost)
                .filter(
                    CompetitorPost.competitor_id == comp.id,
                    CompetitorPost.linkedin_post_id == str(post_id),
                )
                .first()
            )
            if existing:
                # Update engagement numbers
                engagement = raw.get("engagement", {})
                existing.likes = engagement.get("likes", existing.likes)
                existing.comments = engagement.get("comments", existing.comments)
                existing.shares = engagement.get("shares", existing.shares)
                return False

        # Parse engagement data
        engagement = raw.get("engagement", {})
        likes = engagement.get("likes", 0) or 0
        comments = engagement.get("comments", 0) or 0
        shares = engagement.get("shares", 0) or 0

        # Parse date from postedAt object (contains .timestamp in ms)
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

        # Check for media — postImages is a list of {url, width, height}
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

        post = CompetitorPost(
            competitor_id=comp.id,
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
            source="scraped",
        )
        self.db.add(post)
        return True

    def _recalculate_stats(self, comp: Competitor):
        """Recalculate aggregate stats for a competitor."""
        posts = comp.posts
        if not posts:
            comp.total_posts_tracked = 0
            comp.avg_likes = 0
            comp.avg_comments = 0
            comp.avg_shares = 0
            comp.posting_frequency = None
            return

        comp.total_posts_tracked = len(posts)
        comp.avg_likes = round(sum(p.likes for p in posts) / len(posts), 1)
        comp.avg_comments = round(sum(p.comments for p in posts) / len(posts), 1)
        comp.avg_shares = round(sum(p.shares for p in posts) / len(posts), 1)

        # Calculate posting frequency from dates
        dated = sorted([p for p in posts if p.post_date], key=lambda p: p.post_date)
        if len(dated) >= 2:
            span = (dated[-1].post_date - dated[0].post_date).days
            if span > 0:
                posts_per_week = round(len(dated) / (span / 7), 1)
                comp.posting_frequency = f"{posts_per_week}x/week"

    # ── AI Analysis ───────────────────────────────────────────

    def _analyze_unanalyzed_posts(self, comp: Competitor) -> int:
        """Run Claude AI analysis on posts that haven't been analyzed yet."""
        unanalyzed = (
            self.db.query(CompetitorPost)
            .filter(
                CompetitorPost.competitor_id == comp.id,
                CompetitorPost.ai_analyzed.is_(False),
            )
            .limit(10)  # batch to avoid API overload
            .all()
        )

        analyzed = 0
        for post in unanalyzed:
            try:
                self._analyze_post(post, comp.name)
                analyzed += 1
            except Exception as e:
                logger.warning("Failed to analyze post %s: %s", post.id, e)

        if analyzed:
            self.db.commit()
        return analyzed

    def _analyze_post(self, post: CompetitorPost, competitor_name: str):
        """Use Claude to deeply analyze a competitor post."""
        prompt = f"""Analyze this LinkedIn post from competitor "{competitor_name}" and provide a structured breakdown.

POST CONTENT:
---
{post.content}
---

ENGAGEMENT: {post.likes} likes, {post.comments} comments, {post.shares} shares

Respond in EXACTLY this format (fill in each field, keep answers concise):

HOOK_STYLE: [one of: bold_statement, question, story, statistic, contrarian, listicle, personal, how_to, curiosity_gap, challenge]
CONTENT_FORMAT: [one of: list, story, framework, tips, case_study, opinion, educational, motivational, behind_the_scenes, comparison]
TOPIC: [main topic in 3-5 words]
KEY_TAKEAWAY: [the core insight readers got from this post, 1-2 sentences]
WHY_IT_WORKS: [why this post got good engagement — be specific about the psychological triggers, format choices, and content strategy, 2-3 sentences]
HOW_TO_RECREATE: [step-by-step guide on how I can write a similar post for my niche (supplements and health e-commerce) — include the structure to follow, hook template, and content angle to use, 3-4 sentences]"""

        try:
            message = self.claude.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=800,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            result = message.content[0].text.strip()

            # Parse the structured response
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
            post.how_to_recreate = fields.get("how_to_recreate", "")
            post.ai_analyzed = True

            logger.info("Analyzed post #%s: hook=%s, format=%s", post.id, post.hook_style, post.content_format)

        except anthropic.APIError as e:
            logger.error("Claude API error analyzing post %s: %s", post.id, e)
        except Exception as e:
            logger.error("Analysis error for post %s: %s", post.id, e)

    def analyze_single_post(self, post_id: int) -> bool:
        """Analyze a single post on demand."""
        post = self.db.query(CompetitorPost).get(post_id)
        if not post:
            return False
        comp_name = post.competitor.name if post.competitor else "Unknown"
        self._analyze_post(post, comp_name)
        self.db.commit()
        return post.ai_analyzed
