"""Deep research module — enriches research items with extracted data, screenshots, and case studies."""

import json
import logging
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

from config import settings
from database.models import ResearchItem

logger = logging.getLogger(__name__)

SCREENSHOTS_DIR = Path("dashboard/static/images/research")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

DATA_EXTRACTION_PROMPT = """You are a data analyst specializing in e-commerce and digital marketing.

Given a web page's content, extract specific, useful data points that could be used in a LinkedIn post.

Focus on:
- Concrete numbers (percentages, dollar amounts, growth rates, conversion rates)
- Before/after comparisons
- Case study details (brand name, industry, strategy used, results)
- Surprising statistics or trends
- Actionable metrics (AOV, CVR, ROAS, email open rates, etc.)

Return ONLY valid JSON:
{{
  "data_points": [
    {{
      "metric": "Conversion Rate",
      "value": "4.7%",
      "context": "After implementing exit-intent popups",
      "source_type": "case_study"
    }}
  ],
  "case_study": {{
    "brand": "Brand name or null",
    "industry": "Industry or null",
    "strategy": "What they did",
    "result": "Key outcome",
    "before_after": {{"before": "2.1%", "after": "4.7%", "metric": "CVR"}}
  }},
  "key_stats": [
    "67% of shoppers abandon carts due to unexpected shipping costs",
    "Email flows generate 30-40% of Klaviyo revenue for top brands"
  ],
  "content_angle": "Brief suggestion for how to use this data in a LinkedIn post"
}}

If no meaningful data can be extracted, return: {{"data_points": [], "case_study": null, "key_stats": [], "content_angle": null}}

WEB PAGE CONTENT:
{content}
"""


class DeepResearcher:
    """Enriches research items with extracted data points and visual research."""

    def __init__(self, db: Session):
        self.db = db

    async def enrich_research_item(self, item_id: int) -> dict:
        """Fetch the source URL, extract data points, and take a screenshot.

        Returns dict with extracted data and screenshot path.
        """
        item = self.db.query(ResearchItem).filter(ResearchItem.id == item_id).first()
        if not item:
            return {"success": False, "error": "Research item not found"}

        result = {"success": True, "data_extracted": False, "screenshot_taken": False}

        # Extract data from URL content
        if item.url:
            data = await self._extract_data_from_url(item.url)
            if data:
                item.data_points = json.dumps(data)
                result["data_extracted"] = True
                result["data"] = data

            # Take screenshot
            screenshot_path = await self._take_screenshot(item.url, f"research_{item.id}")
            if screenshot_path:
                item.screenshot_path = screenshot_path
                result["screenshot_taken"] = True
                result["screenshot_path"] = screenshot_path

        self.db.commit()
        logger.info(
            "Enriched research item #%s: data=%s, screenshot=%s",
            item_id, result["data_extracted"], result["screenshot_taken"]
        )
        return result

    async def _extract_data_from_url(self, url: str) -> dict | None:
        """Fetch a URL and extract structured data using Claude."""
        try:
            from utils.netguard import fetch_public

            resp = await fetch_public(url, timeout=15.0)
            if resp.status_code != 200:
                logger.warning("Failed to fetch %s: %s", url, resp.status_code)
                return None

            # Extract text content (strip HTML tags roughly)
            content = resp.text
            if "<html" in content.lower():
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(content, "html.parser")
                # Remove script and style elements
                for tag in soup(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                content = soup.get_text(separator="\n", strip=True)

            # Truncate to fit Claude context
            content = content[:8000]

        except Exception as e:
            logger.warning("Failed to fetch URL %s: %s", url, e)
            return None

        # Extract data with Claude
        try:
            import llm

            prompt = DATA_EXTRACTION_PROMPT.format(content=llm.untrusted(content, "web_page"))
            return llm.complete_json_loose("deep_research", prompt, brand=False, effort="low", max_tokens=4000)
        except Exception as e:
            logger.error("Data extraction failed for %s: %s", url, e)
            return None

    async def _take_screenshot(self, url: str, name_prefix: str) -> str | None:
        """Take a screenshot of a URL using Playwright."""
        if not settings.SCREEN_RECORD_ENABLED:
            return None

        from utils.netguard import is_public_url
        if not is_public_url(url):
            logger.warning("Screenshot blocked for non-public URL: %s", url)
            return None

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 800})
                await page.goto(url, wait_until="networkidle", timeout=20000)
                await page.wait_for_timeout(1000)

                filename = f"{name_prefix}.png"
                filepath = SCREENSHOTS_DIR / filename
                await page.screenshot(path=str(filepath), full_page=False)
                await browser.close()

            relative_path = f"/static/images/research/{filename}"
            logger.info("Screenshot taken: %s", relative_path)
            return relative_path

        except Exception as e:
            logger.warning("Screenshot failed for %s: %s", url, e)
            return None

    async def search_case_studies(self, topic: str, limit: int = 5) -> list[dict]:
        """Search for e-commerce case studies related to a topic using web search.

        Returns a list of enriched research data dicts.
        """
        search_queries = [
            f"{topic} e-commerce case study results",
            f"{topic} shopify store conversion rate improvement",
            f"{topic} DTC brand growth metrics",
        ]

        results = []
        async with httpx.AsyncClient() as client:
            for query in search_queries[:2]:
                try:
                    # Use a simple search via DuckDuckGo HTML (no API key needed)
                    resp = await client.get(
                        "https://html.duckduckgo.com/html/",
                        params={"q": query},
                        headers={"User-Agent": "Mozilla/5.0"},
                        timeout=10.0,
                    )
                    if resp.status_code == 200:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for result_div in soup.select(".result__a")[:limit]:
                            url = result_div.get("href", "")
                            title = result_div.get_text(strip=True)
                            if url and title:
                                results.append({
                                    "title": title,
                                    "url": url,
                                    "query": query,
                                })
                except Exception as e:
                    logger.warning("Case study search failed for '%s': %s", query, e)

        # Enrich top results with data extraction
        enriched = []
        for item in results[:3]:
            data = await self._extract_data_from_url(item["url"])
            if data and (data.get("data_points") or data.get("key_stats")):
                item["extracted_data"] = data
                enriched.append(item)

        logger.info("Found %d case studies for '%s' (%d enriched)", len(results), topic, len(enriched))
        return enriched

    async def enrich_for_content_generation(self, topic: str, research_context: str = "") -> dict:
        """Run deep research for a topic to feed into content + GIF generation.

        Returns enriched context with data points, stats, and visual suggestions.
        """
        # Search for case studies
        case_studies = await self.search_case_studies(topic)

        # Compile enriched context
        enriched = {
            "topic": topic,
            "case_studies": case_studies,
            "data_points": [],
            "key_stats": [],
            "gif_data": None,
        }

        # Extract the best data for GIF creation
        for cs in case_studies:
            data = cs.get("extracted_data", {})
            enriched["data_points"].extend(data.get("data_points", []))
            enriched["key_stats"].extend(data.get("key_stats", []))

            # Check for before/after data (great for GIFs)
            case_study = data.get("case_study")
            if case_study and case_study.get("before_after") and not enriched["gif_data"]:
                ba = case_study["before_after"]
                enriched["gif_data"] = {
                    "gif_type": "data_counter",
                    "metric": ba.get("metric", topic),
                    "from_val": ba.get("before", "0"),
                    "to_val": ba.get("after", "100"),
                    "brand": case_study.get("brand"),
                }

        logger.info(
            "Deep research for '%s': %d case studies, %d data points, %d stats, gif_data=%s",
            topic, len(case_studies), len(enriched["data_points"]),
            len(enriched["key_stats"]), bool(enriched["gif_data"]),
        )
        return enriched
