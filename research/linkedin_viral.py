"""LinkedIn viral content researcher — finds high-performing LinkedIn posts for inspiration.

Sources:
1. Competitor posts already in the DB (sorted by engagement)
2. Google search for viral LinkedIn posts in niche
3. User's own top-performing posts for pattern analysis
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from config import settings
from database.models import CompetitorPost, MyLinkedInPost

logger = logging.getLogger(__name__)

# Queries to find viral LinkedIn content via Google
LINKEDIN_SEARCH_QUERIES = [
    "site:linkedin.com e-commerce growth tips",
    "site:linkedin.com DTC brand strategy",
    "site:linkedin.com Shopify store scaling",
    "site:linkedin.com email marketing e-commerce",
    "site:linkedin.com CRO conversion rate optimization",
    "site:linkedin.com agency owner lessons",
    "viral linkedin post marketing 2025",
    "best linkedin posts e-commerce",
]


class LinkedInViralResearcher:
    """Finds high-performing LinkedIn content for research and inspiration."""

    def __init__(self, db: Session):
        self.db = db

    def get_viral_content(self) -> list[dict]:
        """Aggregate viral LinkedIn content from all available sources."""
        results = []

        # Source 1: Top competitor posts from DB
        results.extend(self._get_top_competitor_posts())

        # Source 2: User's own best posts
        results.extend(self._get_own_top_posts())

        # Source 3: Google search for viral LinkedIn posts
        results.extend(self._search_viral_linkedin())

        logger.info("LinkedIn viral research: %d items found", len(results))
        return results

    def _get_top_competitor_posts(self, limit: int = 15) -> list[dict]:
        """Pull highest-engagement competitor posts from DB."""
        posts = (
            self.db.query(CompetitorPost)
            .filter(CompetitorPost.content.isnot(None))
            .order_by(
                (CompetitorPost.likes + CompetitorPost.comments * 3 + CompetitorPost.shares * 5).desc()
            )
            .limit(limit)
            .all()
        )

        results = []
        for p in posts:
            engagement = p.likes + p.comments * 3 + p.shares * 5
            competitor_name = p.competitor.name if p.competitor else "Unknown"

            # Score based on engagement level
            if engagement >= 500:
                relevance = 0.95
            elif engagement >= 200:
                relevance = 0.85
            elif engagement >= 50:
                relevance = 0.7
            else:
                relevance = 0.5

            results.append({
                "topic": p.topic or f"Viral post by {competitor_name}",
                "title": f"[{competitor_name}] {(p.content or '')[:80]}...",
                "content": (
                    f"Engagement: {p.likes} likes, {p.comments} comments, {p.shares} shares\n"
                    f"Hook style: {p.hook_style or 'N/A'}\n"
                    f"Format: {p.content_format or 'N/A'}\n"
                    f"Why it works: {p.why_it_works or 'N/A'}\n\n"
                    f"Post:\n{(p.content or '')[:400]}"
                ),
                "source": "linkedin_competitor",
                "url": p.post_url or "",
                "relevance_score": relevance,
                "region": "global",
                "category": "ecommerce_general",
            })

        logger.info("Found %d top competitor posts", len(results))
        return results

    def _get_own_top_posts(self, limit: int = 10) -> list[dict]:
        """Pull user's own highest-performing LinkedIn posts."""
        posts = (
            self.db.query(MyLinkedInPost)
            .filter(MyLinkedInPost.content.isnot(None))
            .all()
        )

        if not posts:
            return []

        # Sort by engagement score in Python
        scored = []
        for p in posts:
            eng = p.likes + p.comments * 3 + p.shares * 5
            scored.append((p, eng))
        scored.sort(key=lambda x: x[1], reverse=True)

        results = []
        for p, engagement in scored[:limit]:
            if engagement >= 200:
                relevance = 0.9
            elif engagement >= 50:
                relevance = 0.75
            else:
                relevance = 0.6

            results.append({
                "topic": p.topic or "My top LinkedIn post",
                "title": f"[My Post] {(p.content or '')[:80]}...",
                "content": (
                    f"Engagement: {p.likes} likes, {p.comments} comments, {p.shares} shares\n"
                    f"Hook style: {p.hook_style or 'N/A'}\n"
                    f"Format: {p.content_format or 'N/A'}\n"
                    f"Why it works: {p.why_it_works or 'N/A'}\n\n"
                    f"Post:\n{(p.content or '')[:400]}"
                ),
                "source": "linkedin_own",
                "url": p.post_url or "",
                "relevance_score": relevance,
                "region": "global",
                "category": "ecommerce_general",
            })

        logger.info("Found %d own top posts", len(results))
        return results

    def _search_viral_linkedin(self) -> list[dict]:
        """Search Google News for viral LinkedIn content articles."""
        results = []

        try:
            import feedparser

            for query in LINKEDIN_SEARCH_QUERIES[:4]:
                url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
                feed = feedparser.parse(url)

                for entry in feed.entries[:3]:
                    title = entry.get("title", "")
                    content = entry.get("summary", entry.get("description", ""))[:500]

                    results.append({
                        "topic": title,
                        "title": title,
                        "content": content,
                        "source": "linkedin_search",
                        "url": entry.get("link", ""),
                        "relevance_score": 0.65,
                        "region": "global",
                        "category": "agency",
                    })

        except Exception as e:
            logger.error("LinkedIn viral search error: %s", e)

        # Deduplicate by title
        seen = set()
        unique = []
        for r in results:
            key = r["title"].lower()[:50]
            if key not in seen:
                seen.add(key)
                unique.append(r)

        logger.info("Found %d viral LinkedIn search results", len(unique))
        return unique[:15]
