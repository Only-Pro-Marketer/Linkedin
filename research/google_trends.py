"""Google Trends researcher for e-commerce, supplements, and marketing topics."""

import logging

logger = logging.getLogger(__name__)

# Keywords organized by category for trending topic discovery
SEED_KEYWORDS_BY_CATEGORY = {
    "supplements": [
        "supplements", "protein powder", "vitamins", "probiotics",
        "collagen", "creatine", "ashwagandha", "magnesium", "omega 3",
        "pre workout", "gut health", "functional foods", "clean label",
    ],
    "shopify": [
        "Shopify store", "Shopify apps", "Shopify themes",
        "Shopify dropshipping", "Shopify Plus",
    ],
    "cro": [
        "conversion rate optimization", "A/B testing ecommerce",
        "landing page optimization", "checkout optimization",
    ],
    "klaviyo": [
        "Klaviyo", "email marketing ecommerce", "SMS marketing DTC",
        "abandoned cart email", "email flows",
    ],
    "amazon": [
        "Amazon FBA", "Amazon seller", "Amazon PPC",
        "Amazon product launch",
    ],
    "paid_ads": [
        "Facebook ads ecommerce", "Google ads ecommerce",
        "TikTok ads", "paid media ROAS", "Meta ads",
    ],
    "tiktok_shop": [
        "TikTok Shop", "social commerce", "live shopping",
        "TikTok affiliate",
    ],
    "dtc": [
        "DTC brands", "direct to consumer", "DTC growth",
        "subscription ecommerce",
    ],
    "ecommerce_general": [
        "ecommerce trends", "online retail", "ecommerce growth",
        "headless commerce", "composable commerce",
    ],
}

# Flatten for backward compatibility
SEED_KEYWORDS = []
for _kws in SEED_KEYWORDS_BY_CATEGORY.values():
    SEED_KEYWORDS.extend(_kws)

# Regions to scan with pytrends geo codes
GEO_REGIONS = [
    ("north_america", "US", "united_states"),
    ("uk", "GB", "united_kingdom"),
]

# Broadened relevance filter — matches health/supplement AND e-commerce terms
RELEVANCE_KEYWORDS = {
    # Health/supplement
    "health", "supplement", "vitamin", "protein", "wellness",
    "nutrition", "diet", "fitness", "fda", "organic", "natural",
    "weight", "gut", "immune", "energy", "sleep",
    # E-commerce
    "ecommerce", "e-commerce", "shopify", "amazon", "klaviyo",
    "tiktok", "dtc", "brand", "retail", "ads", "marketing",
    "conversion", "cro", "email", "cart", "checkout", "subscription",
    "agency", "growth", "revenue", "store", "seller", "shop",
    "facebook", "google ads", "meta", "influencer",
}


class GoogleTrendsResearcher:
    """Uses pytrends to find trending topics in e-commerce and health."""

    def get_trending_searches(self, geo: str = "US") -> list[dict]:
        """Get daily trending searches filtered for relevance, across multiple regions."""
        results = []

        for region_name, geo_code, pn_name in GEO_REGIONS:
            try:
                from pytrends.request import TrendReq

                pytrends = TrendReq(hl="en-US", tz=360)
                trending = pytrends.trending_searches(pn=pn_name)

                for _, row in trending.iterrows():
                    term = str(row[0]).lower()
                    if any(kw in term for kw in RELEVANCE_KEYWORDS):
                        category = self._detect_category(term)
                        results.append({
                            "topic": str(row[0]),
                            "source": "google_trends",
                            "relevance_score": 0.8,
                            "region": region_name,
                            "category": category,
                        })

                logger.info("Found %d relevant trends for %s", len(results), region_name)

            except Exception as e:
                logger.error("Google Trends error for %s: %s", region_name, e)

        return results

    def get_related_queries(
        self,
        keyword: str = "supplements",
        region: str = "global",
        category: str = "ecommerce_general",
    ) -> list[dict]:
        """Get rising and top related queries for a keyword."""
        try:
            from pytrends.request import TrendReq

            pytrends = TrendReq(hl="en-US", tz=360)
            pytrends.build_payload([keyword], timeframe="now 7-d")
            related = pytrends.related_queries()

            results = []
            if keyword in related and related[keyword]["rising"] is not None:
                rising = related[keyword]["rising"]
                for _, row in rising.head(10).iterrows():
                    detected_cat = self._detect_category(row["query"])
                    results.append({
                        "topic": row["query"],
                        "source": "google_trends_related",
                        "relevance_score": min(float(row.get("value", 50)) / 100, 1.0),
                        "region": region,
                        "category": detected_cat or category,
                    })

            logger.info("Found %d related queries for '%s'", len(results), keyword)
            return results

        except Exception as e:
            logger.error("Related queries error for '%s': %s", keyword, e)
            return []

    def _detect_category(self, text: str) -> str:
        """Infer category from text content."""
        text_lower = text.lower()
        category_signals = {
            "supplements": [
                "supplement", "vitamin", "protein", "probiotic", "collagen",
                "creatine", "ashwagandha", "omega", "gut health", "nutra",
                "pre workout", "clean label", "functional food",
            ],
            "shopify": ["shopify"],
            "klaviyo": [
                "klaviyo", "email marketing", "email flow", "abandoned cart",
                "sms marketing",
            ],
            "amazon": ["amazon", "fba", "seller central"],
            "paid_ads": [
                "facebook ads", "google ads", "meta ads", "tiktok ads",
                "paid media", "roas", "ppc", "cpc",
            ],
            "tiktok_shop": ["tiktok shop", "social commerce", "live shopping"],
            "cro": [
                "conversion rate", "cro", "a/b test", "landing page",
                "checkout optimiz",
            ],
            "dtc": ["dtc", "direct to consumer", "d2c", "subscription box"],
            "agency": ["agency", "consulting"],
        }
        for cat, signals in category_signals.items():
            if any(sig in text_lower for sig in signals):
                return cat
        return "ecommerce_general"
