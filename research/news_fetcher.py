"""Industry news fetcher — RSS feeds and web sources across regions."""

import logging
import random
from datetime import datetime

import feedparser

logger = logging.getLogger(__name__)

# (name, url, region, category)
RSS_FEEDS = [
    # ── Supplements ──
    ("Nutra Ingredients US", "https://www.nutraingredients-usa.com/rss/news", "north_america", "supplements"),
    ("Nutra Ingredients EU", "https://www.nutraingredients.com/rss/news", "europe", "supplements"),
    ("Natural Products Insider", "https://www.naturalproductsinsider.com/rss.xml", "north_america", "supplements"),
    ("Nutritional Outlook", "https://www.nutritionaloutlook.com/rss", "north_america", "supplements"),

    # ── E-commerce General ──
    ("Practical Ecommerce", "https://pec-ly.com/feed", "global", "ecommerce_general"),
    ("Digital Commerce 360", "https://www.digitalcommerce360.com/feed/", "north_america", "ecommerce_general"),
    ("Retail Dive", "https://www.retaildive.com/feeds/news/", "north_america", "ecommerce_general"),

    # ── Shopify ──
    ("Shopify Blog", "https://www.shopify.com/blog/feed", "global", "shopify"),
    ("Shopify Partners Blog", "https://www.shopify.com/partners/blog/feed", "global", "shopify"),

    # ── Email Marketing / Klaviyo ──
    ("Klaviyo Blog", "https://www.klaviyo.com/blog/feed", "global", "klaviyo"),
    ("Litmus Blog", "https://www.litmus.com/blog/feed", "global", "klaviyo"),

    # ── CRO ──
    ("CXL Blog", "https://cxl.com/blog/feed/", "global", "cro"),

    # ── Amazon ──
    ("Jungle Scout Blog", "https://www.junglescout.com/blog/feed/", "north_america", "amazon"),

    # ── DTC / Agency ──
    ("2PM Inc", "https://2pml.com/feed", "north_america", "dtc"),
    ("Marketing Brew", "https://www.marketingbrew.com/feed", "north_america", "agency"),

    # ── UK / Europe ──
    ("Internet Retailing UK", "https://internetretailing.net/feed/", "uk", "ecommerce_general"),
    ("Ecommerce News EU", "https://ecommercenews.eu/feed/", "europe", "ecommerce_general"),
    ("Retail Gazette UK", "https://www.retailgazette.co.uk/feed/", "uk", "ecommerce_general"),

    # ── Paid Ads ──
    ("Search Engine Land", "https://searchengineland.com/feed", "global", "paid_ads"),
    ("PPC Hero", "https://www.ppchero.com/feed/", "global", "paid_ads"),
    ("Jon Loomer", "https://www.jonloomer.com/feed/", "north_america", "paid_ads"),

    # ── TikTok Shop / Social Commerce ──
    ("Social Media Today", "https://www.socialmediatoday.com/feed/", "global", "tiktok_shop"),
    ("Later Blog", "https://later.com/blog/feed/", "global", "tiktok_shop"),
]

# (query, region, category, google_news_params)
REGIONAL_NEWS_QUERIES = [
    # ── Supplements ──
    ("supplement industry news 2026", "north_america", "supplements", "hl=en-US&gl=US&ceid=US:en"),
    ("supplement brand ecommerce", "north_america", "supplements", "hl=en-US&gl=US&ceid=US:en"),
    ("supplement industry UK", "uk", "supplements", "hl=en-GB&gl=GB&ceid=GB:en"),
    ("health supplement market Europe", "europe", "supplements", "hl=en&gl=DE&ceid=DE:en"),
    ("FDA supplement regulation", "north_america", "supplements", "hl=en-US&gl=US&ceid=US:en"),

    # ── CRO ──
    ("conversion rate optimization ecommerce", "global", "cro", "hl=en-US&gl=US&ceid=US:en"),
    ("CRO A/B testing ecommerce", "global", "cro", "hl=en-US&gl=US&ceid=US:en"),

    # ── Shopify ──
    ("Shopify store growth tips", "north_america", "shopify", "hl=en-US&gl=US&ceid=US:en"),
    ("Shopify ecommerce trends", "global", "shopify", "hl=en-US&gl=US&ceid=US:en"),
    ("Shopify UK merchants", "uk", "shopify", "hl=en-GB&gl=GB&ceid=GB:en"),

    # ── Klaviyo / Email ──
    ("Klaviyo email marketing ecommerce", "global", "klaviyo", "hl=en-US&gl=US&ceid=US:en"),
    ("email marketing DTC brands", "north_america", "klaviyo", "hl=en-US&gl=US&ceid=US:en"),

    # ── Amazon ──
    ("Amazon FBA seller news", "north_america", "amazon", "hl=en-US&gl=US&ceid=US:en"),
    ("Amazon marketplace UK", "uk", "amazon", "hl=en-GB&gl=GB&ceid=GB:en"),
    ("Amazon Europe seller", "europe", "amazon", "hl=en&gl=DE&ceid=DE:en"),

    # ── Paid Ads ──
    ("Facebook ads ecommerce 2026", "global", "paid_ads", "hl=en-US&gl=US&ceid=US:en"),
    ("Google ads ecommerce strategy", "global", "paid_ads", "hl=en-US&gl=US&ceid=US:en"),
    ("paid media DTC brands", "north_america", "paid_ads", "hl=en-US&gl=US&ceid=US:en"),

    # ── TikTok Shop ──
    ("TikTok Shop ecommerce", "north_america", "tiktok_shop", "hl=en-US&gl=US&ceid=US:en"),
    ("TikTok Shop UK sellers", "uk", "tiktok_shop", "hl=en-GB&gl=GB&ceid=GB:en"),
    ("social commerce trends Europe", "europe", "tiktok_shop", "hl=en&gl=DE&ceid=DE:en"),

    # ── DTC / Agency ──
    ("DTC brand growth strategy", "north_america", "dtc", "hl=en-US&gl=US&ceid=US:en"),
    ("ecommerce agency trends", "global", "agency", "hl=en-US&gl=US&ceid=US:en"),
    ("DTC brands UK growth", "uk", "dtc", "hl=en-GB&gl=GB&ceid=GB:en"),

    # ── E-commerce General ──
    ("ecommerce industry trends 2026", "north_america", "ecommerce_general", "hl=en-US&gl=US&ceid=US:en"),
    ("ecommerce trends UK 2026", "uk", "ecommerce_general", "hl=en-GB&gl=GB&ceid=GB:en"),
    ("ecommerce Europe growth", "europe", "ecommerce_general", "hl=en&gl=DE&ceid=DE:en"),
]


def detect_region_from_text(title: str, content: str = "", url: str = "") -> str:
    """Heuristic to detect geographic region from article metadata."""
    text = f"{title} {content} {url}".lower()

    uk_signals = [
        ".co.uk", "uk ", "u.k.", "united kingdom", "britain", "british",
        "london", "england", "scotland", "wales", "bbc", "guardian",
        "telegraph", "retail gazette", "internet retailing",
        "pounds", "gbp", "ofcom", "hmrc",
    ]
    europe_signals = [
        "europe", "european", "eu ", "gdpr", "germany", "german",
        "france", "french", "spain", "spanish", "italy", "italian",
        "netherlands", "dutch", "sweden", "nordic", "belgium",
        "ecommercenews.eu", "nutraingredients.com",
    ]
    na_signals = [
        "us ", "u.s.", "usa", "united states", "america", "american",
        "canada", "canadian", "fda", "ftc", "amazon.com",
        "wall street", "silicon valley", "new york", "california",
        "toronto",
    ]

    uk_score = sum(1 for s in uk_signals if s in text)
    eu_score = sum(1 for s in europe_signals if s in text)
    na_score = sum(1 for s in na_signals if s in text)

    if uk_score > eu_score and uk_score > na_score and uk_score > 0:
        return "uk"
    if eu_score > uk_score and eu_score > na_score and eu_score > 0:
        return "europe"
    if na_score > 0:
        return "north_america"
    return "global"


class NewsFetcher:
    """Fetches industry news from RSS feeds across regions and categories."""

    def fetch_from_rss(self) -> list[dict]:
        """Pull latest articles from RSS feeds."""
        results = []

        for name, url, region, category in RSS_FEEDS:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:5]:
                    results.append({
                        "title": entry.get("title", ""),
                        "content": entry.get("summary", entry.get("description", ""))[:500],
                        "source": f"rss_{name}",
                        "url": entry.get("link", ""),
                        "topic": entry.get("title", ""),
                        "relevance_score": 0.6,
                        "region": region,
                        "category": category,
                    })
            except Exception as e:
                logger.error("RSS fetch error for %s: %s", name, e)
                continue

        logger.info("Fetched %d articles from RSS feeds", len(results))
        return results

    def fetch_google_news(
        self,
        query: str = "supplement industry news",
        region: str = "global",
        category: str = "ecommerce_general",
        params: str = "hl=en-US&gl=US&ceid=US:en",
    ) -> list[dict]:
        """Search Google News RSS for industry news."""
        try:
            url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&{params}"
            feed = feedparser.parse(url)
            results = []

            for entry in feed.entries[:10]:
                results.append({
                    "title": entry.get("title", ""),
                    "content": entry.get("summary", entry.get("description", ""))[:500],
                    "source": "google_news",
                    "url": entry.get("link", ""),
                    "topic": entry.get("title", ""),
                    "relevance_score": 0.7,
                    "region": region,
                    "category": category,
                })

            logger.info("Found %d Google News results for '%s'", len(results), query)
            return results

        except Exception as e:
            logger.error("Google News error for '%s': %s", query, e)
            return []

    def fetch_all_news(self) -> list[dict]:
        """Fetch news from all sources."""
        results = self.fetch_from_rss()

        # Cycle 8 random queries per run to avoid rate limiting
        queries_this_cycle = random.sample(
            REGIONAL_NEWS_QUERIES,
            min(8, len(REGIONAL_NEWS_QUERIES)),
        )
        for query, region, category, params in queries_this_cycle:
            results.extend(self.fetch_google_news(query, region, category, params))

        # Deduplicate by title similarity
        seen_titles = set()
        unique = []
        for r in results:
            title_key = r["title"].lower()[:50]
            if title_key not in seen_titles:
                seen_titles.add(title_key)
                unique.append(r)

        logger.info("Total unique news items: %d", len(unique))
        return unique
