"""Reddit researcher — monitors supplement and e-commerce subreddits."""

import logging

from config import settings

logger = logging.getLogger(__name__)

SUBREDDITS = [
    "supplements",
    "nutrition",
    "ecommerce",
    "Entrepreneur",
    "smallbusiness",
    "FulfillmentByAmazon",
    "Nootropics",
    "Fitness",
]


class RedditResearcher:
    """Uses PRAW to find trending discussions in health/supplement subreddits."""

    def __init__(self):
        self._reddit = None

    def _get_reddit(self):
        """Lazy-init the Reddit client."""
        if self._reddit is None:
            if not settings.REDDIT_CLIENT_ID:
                return None
            try:
                import praw

                self._reddit = praw.Reddit(
                    client_id=settings.REDDIT_CLIENT_ID,
                    client_secret=settings.REDDIT_CLIENT_SECRET,
                    user_agent=settings.REDDIT_USER_AGENT,
                )
            except Exception as e:
                logger.error("Failed to init Reddit client: %s", e)
                return None
        return self._reddit

    def get_hot_topics(self, subreddit_name: str = "supplements", limit: int = 15) -> list[dict]:
        """Get hot posts from a subreddit."""
        reddit = self._get_reddit()
        if not reddit:
            return []

        try:
            subreddit = reddit.subreddit(subreddit_name)
            results = []

            for post in subreddit.hot(limit=limit):
                if post.stickied:
                    continue
                results.append({
                    "topic": post.title,
                    "content": (post.selftext or "")[:500],
                    "source": f"reddit_r/{subreddit_name}",
                    "url": f"https://reddit.com{post.permalink}",
                    "relevance_score": min(post.score / 100, 1.0),
                    "title": post.title,
                })

            logger.info("Found %d hot posts in r/%s", len(results), subreddit_name)
            return results

        except Exception as e:
            logger.error("Reddit error for r/%s: %s", subreddit_name, e)
            return []

    def get_trending_discussions(self) -> list[dict]:
        """Scan all monitored subreddits for trending health/supplement discussions."""
        all_results = []
        for sub in SUBREDDITS:
            results = self.get_hot_topics(sub, limit=10)
            all_results.extend(results)

        # Sort by relevance score
        all_results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
        logger.info("Found %d total trending discussions across all subreddits", len(all_results))
        return all_results[:30]  # Top 30
