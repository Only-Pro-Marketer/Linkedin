"""Content strategy engine — decides WHAT to post and HOW."""

import random
from datetime import datetime

from sqlalchemy.orm import Session

from content.templates.template_library import get_all_templates, BUILTIN_TEMPLATES
from database.models import (
    InsightCategory,
    LearningInsight,
    QueuedPost,
    PostStatus,
    ResearchItem,
    TemplateRecord,
)
from existing_tool.models import PostTemplate


# Tone rotation for variety
TONES = ["authoritative", "conversational", "provocative", "vulnerable", "data-driven"]

# Angles that map to different content styles
ANGLES = [
    "personal_story — 'I did X and learned Y'",
    "data_insight — 'The numbers show X'",
    "contrarian_take — 'Everyone thinks X, but actually Y'",
    "how_to — 'Here is exactly how to do X step by step'",
    "newsjack — 'X just happened, here is what it means for our industry'",
    "myth_buster — 'Stop doing X. Here is why.'",
    "case_study — 'Brand X did Y and got Z results'",
]

# Default topic categories — customize these for your niche.
# Update soul/soul.md "Content Pillars" to match your chosen topics.
# Weights in TOPIC_WEIGHTS below control how often each category is selected.
TOPIC_CATEGORIES = [
    "CRO and conversion optimization tactics from client work",
    "e-commerce operations, margins, and scaling challenges",
    "email and SMS marketing strategies (Klaviyo flows, campaigns, revenue)",
    "agency lessons and founder stories",
    "industry trends (new platforms, AI in e-commerce, Shopify updates)",
    "paid ads and media buying (Meta, TikTok, scaling spend, ROAS)",
    "Amazon and marketplace strategy (PPC, listings, multi-channel)",
    "Shopify development and tech stack optimization",
    "client success patterns — what separates brands that scale vs. stall",
    "customer retention and lifetime value strategies",
]

TOPIC_WEIGHTS = {
    "industry trends (new platforms, AI in e-commerce, Shopify updates)": 2.5,
    "agency lessons and founder stories": 2.0,
    "CRO and conversion optimization tactics from client work": 1.5,
    "client success patterns — what separates brands that scale vs. stall": 1.5,
    "paid ads and media buying (Meta, TikTok, scaling spend, ROAS)": 1.0,
    "email and SMS marketing strategies (Klaviyo flows, campaigns, revenue)": 1.0,
    "e-commerce operations, margins, and scaling challenges": 0.8,
    "Shopify development and tech stack optimization": 0.7,
    "Amazon and marketplace strategy (PPC, listings, multi-channel)": 0.5,
    "customer retention and lifetime value strategies": 0.5,
}


# Media type selection rules — maps angle/template patterns to preferred media
MEDIA_TYPE_RULES = {
    # Angles that work best with GIFs
    "case_study": "gif",
    "data_insight": "gif",
    "how_to": "gif",
    "myth_buster": "gif",
    # Angles that work best with static images
    "personal_story": "image",
    "newsjack": "image",
    # Angles that can go either way
    "contrarian_take": "text",
}


def select_media_type(topic: str, template_name: str, angle: str, research_context: str = "") -> str:
    """Decide whether a post should get a GIF, image, or stay text-only.

    Returns: "gif", "image", or "none"
    """
    # Extract angle key (before the dash)
    angle_key = angle.split("—")[0].strip().replace(" ", "_") if "—" in angle else angle

    # Check angle-based rules
    media = MEDIA_TYPE_RULES.get(angle_key)
    if media:
        if media == "text":
            return "none"
        return media

    # Template-based heuristics
    name = template_name.lower()
    if any(kw in name for kw in ["data", "framework", "tips", "myth"]):
        return "gif"
    if any(kw in name for kw in ["story", "lesson", "origin"]):
        return "image"

    # If research has data points (numbers in context), prefer GIF
    if research_context and any(c.isdigit() for c in research_context):
        return "gif"

    # Topic-based: data-heavy topics favor GIFs
    topic_lower = topic.lower()
    if any(kw in topic_lower for kw in ["cro", "conversion", "revenue", "roas", "aov", "metrics"]):
        return "gif"

    # Default: text-only (text posts outperform image posts 82 vs 5.2 avg likes)
    return "none"


class ContentStrategy:
    """Decides what template, topic, tone, and angle to use for each post."""

    def __init__(self, db: Session):
        self.db = db
        self._insights_cache: dict = {}  # category -> parsed list

    def plan_next_posts(self, count: int = 5) -> list[dict]:
        """Plan the next N posts ensuring variety across templates, topics, and tones.

        Content mix rules:
        - No more than 2 consecutive posts of the same template type
        - Ensure personal/story posts appear at least 1 in every 5
        - Ensure AI/tech topics appear at least 1 in every 5
        """
        templates = get_all_templates()
        recent_posts = self._get_recent_posts(limit=20)
        recent_templates = [p.template_name for p in recent_posts if p.template_name]
        recent_topics = [p.topic for p in recent_posts if p.topic]
        unused_research = self._get_unused_research(limit=count * 2)

        plans = []
        used_templates_this_batch = []
        used_tones_this_batch = []
        taken_research_ids: set[int] = set()

        for i in range(count):
            template = self._select_template(
                templates, recent_templates + used_templates_this_batch
            )

            # Anti-repeat: if last 2 templates are the same, force a different one
            all_recent = recent_templates + used_templates_this_batch
            if len(all_recent) >= 2 and all_recent[-1] == all_recent[-2] == template.name:
                others = [t for t in templates if t.name != template.name]
                if others:
                    template = random.choice(others)

            topic, research_context, research_item = self._select_topic(
                unused_research, taken_research_ids
            )

            # Content mix: ensure at least 1 personal story per batch of 5
            if i == count - 1 and count >= 4:
                has_story = any(
                    "story" in p.get("angle", "").lower() or "personal" in p.get("angle", "").lower()
                    for p in plans
                )
                if not has_story:
                    topic = "agency lessons and founder stories"
                    research_context = ""
                    research_item = None

            tone = self._select_tone(used_tones_this_batch)
            angle = self._select_angle(template, tone)

            plans.append(
                {
                    "template": template,
                    "topic": topic,
                    "tone": tone,
                    "angle": angle,
                    "research_context": research_context,
                    # Marked used only once the post is saved (see generator)
                    "research_item_id": research_item.id if research_item else None,
                }
            )

            used_templates_this_batch.append(template.name)
            used_tones_this_batch.append(tone)

        return plans

    def _select_template(
        self, templates: list[PostTemplate], recent_names: list[str]
    ) -> PostTemplate:
        """Select a template, avoiding recent repeats. Uses learning insights for weighting."""
        # Filter out recently used (last 5)
        recent_set = set(recent_names[-5:])
        available = [t for t in templates if t.name not in recent_set]

        if not available:
            available = templates

        # Weight by DB performance if available
        template_records = {
            r.name: r
            for r in self.db.query(TemplateRecord).all()
        }

        # Get template insights from learning system
        template_insights = self._get_insights_map(InsightCategory.TEMPLATE)

        weighted = []
        for t in available:
            record = template_records.get(t.name)
            weight = 1.0
            if record and record.avg_performance > 0:
                weight = 1.0 + record.avg_performance
            # Apply learning insight boost/penalty
            for insight in template_insights:
                evidence = insight.get("evidence", {})
                if evidence.get("template") == t.name:
                    ratio = evidence.get("ratio")
                    if ratio is None:
                        avg, overall = evidence.get("avg_score", 0), evidence.get("overall_avg", 0)
                        ratio = avg / overall if overall > 0 and avg > 0 else 1.0
                    if ratio > 1.0:
                        weight *= 1.0 + (ratio - 1.0) * 0.5  # Moderate boost
                    elif ratio < 1.0:
                        weight *= max(0.3, ratio)  # Moderate penalty, floor at 0.3
            weighted.append((t, weight))

        templates_list = [t for t, _ in weighted]
        weights = [w for _, w in weighted]
        total = sum(weights)
        weights = [w / total for w in weights]

        return random.choices(templates_list, weights=weights, k=1)[0]

    def _select_topic(
        self,
        research_items: list[ResearchItem],
        taken_ids: set[int],
    ) -> tuple[str, str, ResearchItem | None]:
        """Select a topic — prefer the best unused research item, else a category."""
        available = [r for r in research_items if not r.used and r.id not in taken_ids]
        if available:
            item = available[0]  # list is already sorted by relevance
            taken_ids.add(item.id)
            context = f"Source: {item.source}\nTitle: {item.title or ''}\n{(item.content or '')[:500]}"
            return item.topic or item.title or "industry news", context, item

        # Fall back to weighted random selection from topic categories
        weights = [TOPIC_WEIGHTS.get(cat, 1.0) for cat in TOPIC_CATEGORIES]
        total = sum(weights)
        weights = [w / total for w in weights]
        category = random.choices(TOPIC_CATEGORIES, weights=weights, k=1)[0]
        return category, "", None

    def _select_tone(self, used_this_batch: list[str]) -> str:
        """Rotate through tones, avoiding repeats. Uses learning insights for weighting."""
        available = [t for t in TONES if t not in used_this_batch]
        if not available:
            available = TONES

        # Check tone insights from learning system
        tone_insights = self._get_insights_map(InsightCategory.TONE)
        if not tone_insights:
            return random.choice(available)

        # Build weighted selection based on insights
        weights = []
        for tone in available:
            w = 1.0
            for insight in tone_insights:
                evidence = insight.get("evidence", {})
                if evidence.get("tone") == tone:
                    ratio = evidence.get("ratio", 1.0) if "ratio" in evidence else 1.0
                    # Compute ratio from avg_score/overall_avg if not stored directly
                    avg = evidence.get("avg_score", 0)
                    overall = evidence.get("overall_avg", 0)
                    if overall > 0 and avg > 0:
                        ratio = avg / overall
                    if ratio > 1.0:
                        w *= 1.0 + (ratio - 1.0) * 0.5
                    elif ratio < 1.0:
                        w *= max(0.3, ratio)
            weights.append(w)

        total = sum(weights)
        weights = [w / total for w in weights]
        return random.choices(available, weights=weights, k=1)[0]

    def _select_angle(self, template: PostTemplate, tone: str) -> str:
        """Pick an angle that fits the template and tone."""
        # Map template names to natural angles
        name_lower = template.name.lower()

        if "story" in name_lower or "narrative" in name_lower or "origin" in name_lower:
            return "personal_story — 'I did X and learned Y'"
        if "data" in name_lower or "statistic" in name_lower:
            return "data_insight — 'The numbers show X'"
        if "contrarian" in name_lower or "myth" in name_lower:
            return "contrarian_take — 'Everyone thinks X, but actually Y'"
        if "framework" in name_lower or "tips" in name_lower:
            return "how_to — 'Here is exactly how to do X step by step'"
        if "failure" in name_lower or "lesson" in name_lower or "comeback" in name_lower:
            return "personal_story — 'I did X and learned Y'"
        # Kleo-inspired template mappings
        if "aida" in name_lower or "pas" in name_lower:
            return "how_to — 'Here is exactly how to do X step by step'"
        if "authority" in name_lower:
            return "case_study — 'Brand X did Y and got Z results'"
        if "slippery" in name_lower:
            return "data_insight — 'The numbers show X'"
        if "transformation" in name_lower or "vulnerable" in name_lower:
            return "personal_story — 'I did X and learned Y'"
        if "conflict" in name_lower:
            return "personal_story — 'I did X and learned Y'"
        if "do this not that" in name_lower:
            return "contrarian_take — 'Everyone thinks X, but actually Y'"

        return random.choice(ANGLES)

    def _get_recent_posts(self, limit: int = 20) -> list[QueuedPost]:
        """Get recent posts to avoid repeats."""
        return (
            self.db.query(QueuedPost)
            .filter(
                QueuedPost.status.in_(
                    [PostStatus.QUEUED, PostStatus.APPROVED, PostStatus.POSTED]
                )
            )
            .order_by(QueuedPost.created_at.desc())
            .limit(limit)
            .all()
        )

    def _get_unused_research(self, limit: int = 10) -> list[ResearchItem]:
        """Get research items not yet used for post generation."""
        return (
            self.db.query(ResearchItem)
            .filter(ResearchItem.used == False)
            .order_by(ResearchItem.relevance_score.desc())
            .limit(limit)
            .all()
        )

    def _get_insights_map(self, category: InsightCategory) -> list[dict]:
        """Get active learning insights for a category with parsed evidence (cached per instance)."""
        if category in self._insights_cache:
            return self._insights_cache[category]

        import json
        insights = (
            self.db.query(LearningInsight)
            .filter(
                LearningInsight.category == category,
                LearningInsight.is_active == True,
                LearningInsight.confidence >= 0.4,
            )
            .all()
        )
        result = []
        for i in insights:
            evidence = {}
            if i.evidence_json:
                try:
                    evidence = json.loads(i.evidence_json)
                except (json.JSONDecodeError, TypeError):
                    pass
            result.append({"insight": i, "evidence": evidence})
        self._insights_cache[category] = result
        return result
