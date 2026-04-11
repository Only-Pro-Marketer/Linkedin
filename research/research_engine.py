"""Research engine orchestrator — coordinates all research sources."""

import logging
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from database.models import ResearchItem
from research.google_trends import GoogleTrendsResearcher
from research.linkedin_viral import LinkedInViralResearcher
from research.news_fetcher import NewsFetcher
from research.reddit_scraper import RedditResearcher
from research.trending_topics import rank_topics, _normalize_topic

logger = logging.getLogger(__name__)


class ResearchEngine:
    """Orchestrates research across Google Trends, Reddit, news, and LinkedIn."""

    def __init__(self, db: Session):
        self.db = db
        self.trends = GoogleTrendsResearcher()
        self.reddit = RedditResearcher()
        self.news = NewsFetcher()
        self.linkedin = LinkedInViralResearcher(db)

    def run_research_cycle(self) -> list[ResearchItem]:
        """Execute a full research cycle across all sources.

        Called by the scheduler every 6 hours.
        Returns list of new ResearchItem records stored in the database.
        """
        logger.info("Starting research cycle...")
        all_items = []

        # Google Trends
        try:
            from research.google_trends import SEED_KEYWORDS_BY_CATEGORY

            trending = self.trends.get_trending_searches()
            all_items.extend(trending)

            # Cycle through 3 random categories, 2 keywords each
            categories_this_cycle = random.sample(
                list(SEED_KEYWORDS_BY_CATEGORY.keys()),
                min(3, len(SEED_KEYWORDS_BY_CATEGORY)),
            )
            for cat in categories_this_cycle:
                kws = random.sample(
                    SEED_KEYWORDS_BY_CATEGORY[cat],
                    min(2, len(SEED_KEYWORDS_BY_CATEGORY[cat])),
                )
                for keyword in kws:
                    related = self.trends.get_related_queries(
                        keyword, region="global", category=cat,
                    )
                    all_items.extend(related)
        except Exception as e:
            logger.error("Google Trends research failed: %s", e)

        # Reddit
        try:
            discussions = self.reddit.get_trending_discussions()
            all_items.extend(discussions)
        except Exception as e:
            logger.error("Reddit research failed: %s", e)

        # News
        try:
            news = self.news.fetch_all_news()
            all_items.extend(news)
        except Exception as e:
            logger.error("News research failed: %s", e)

        # LinkedIn viral content
        try:
            linkedin = self.linkedin.get_viral_content()
            all_items.extend(linkedin)
        except Exception as e:
            logger.error("LinkedIn viral research failed: %s", e)

        # Rank and deduplicate
        ranked = rank_topics(all_items, limit=50)

        # Build velocity map from recent items (last 14 days)
        existing_topics = {}
        try:
            recent_items = (
                self.db.query(ResearchItem)
                .filter(ResearchItem.fetched_at >= datetime.utcnow() - timedelta(days=14))
                .all()
            )
            for ri in recent_items:
                key = ri.normalized_topic_key or _normalize_topic(ri.topic or "")
                if key and key not in existing_topics:
                    existing_topics[key] = {
                        "first_seen_at": ri.first_seen_at or ri.fetched_at,
                        "appearance_count": ri.appearance_count or 1,
                        "prev_relevance": ri.relevance_score or 0,
                    }
        except Exception as e:
            logger.warning("Velocity lookup failed (non-fatal): %s", e)

        # Store in database with velocity data
        stored = []
        for item in ranked:
            norm_key = _normalize_topic(item.get("topic", ""))
            existing = existing_topics.get(norm_key)

            first_seen = datetime.utcnow()
            appearance_count = 1
            velocity = "new"

            if existing:
                first_seen = existing["first_seen_at"]
                appearance_count = existing["appearance_count"] + 1
                prev_rel = existing["prev_relevance"]
                cur_rel = item.get("relevance_score", 0)
                if cur_rel > prev_rel + 0.05:
                    velocity = "rising"
                elif cur_rel < prev_rel - 0.05:
                    velocity = "falling"
                else:
                    velocity = "stable"

            research = ResearchItem(
                source=item.get("source", "unknown"),
                topic=item.get("topic", ""),
                title=item.get("title", item.get("topic", "")),
                content=item.get("content", ""),
                url=item.get("url"),
                relevance_score=item.get("relevance_score", 0.5),
                used=False,
                region=item.get("region"),
                category=item.get("category"),
                normalized_topic_key=norm_key,
                first_seen_at=first_seen,
                appearance_count=appearance_count,
                velocity=velocity,
            )
            self.db.add(research)
            stored.append(research)

        self.db.commit()
        logger.info(
            "Research cycle complete: %d items collected, %d stored",
            len(all_items),
            len(stored),
        )
        return stored

    def get_trending_topics(self, limit: int = 20) -> list[ResearchItem]:
        """Get the most recent high-relevance research items."""
        return (
            self.db.query(ResearchItem)
            .filter(ResearchItem.used == False)
            .order_by(ResearchItem.relevance_score.desc())
            .limit(limit)
            .all()
        )
