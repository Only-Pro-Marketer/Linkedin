"""Content generation orchestrator — Claude writes, the quality pipeline checks and queues."""

import logging
import random

from sqlalchemy.orm import Session

import llm
from config import settings
from content.brand import get_niche
from content.content_strategy import ContentStrategy
from content.pipeline import create_queued_post
from content.prompt_builder import (
    WRITING_RULES,
    build_generation_prompt,
    build_idea_prompt,
    build_recreate_prompt,
    build_regeneration_prompt,
)
from database.models import QueuedPost

logger = logging.getLogger(__name__)


def _formula_id(template_name: str) -> str | None:
    head = (template_name or "").split(" ", 1)[0]
    return head if head[:1] == "F" and head[1:].isdigit() else None


class ContentGenerator:
    """Generates LinkedIn posts with Claude and queues them through the quality pipeline."""

    def __init__(self, db: Session):
        self.db = db
        self.last_error: str | None = None  # user-facing reason for the last failure
        self.strategy = ContentStrategy(db)
        from analytics.learning_context import LearningContext
        self.learning_context = LearningContext(db)

    # ── Public entry points ───────────────────────────────────

    def generate_batch(self, count: int = 5) -> list[QueuedPost]:
        """Generate a batch of posts using content strategy planning."""
        posts = []
        for plan in self.strategy.plan_next_posts(count=count):
            try:
                post = self._generate_from_plan(plan)
                if post:
                    posts.append(post)
            except Exception:
                logger.exception("Failed to generate a post")
        logger.info("Generated %d/%d posts", len(posts), count)
        return posts

    def generate_single(self, template_name: str | None = None, topic: str = "",
                        tone: str = "authoritative") -> QueuedPost | None:
        """Generate one post, optionally with a specific template and topic."""
        from content.templates.template_library import get_all_templates, get_template_by_name

        template = get_template_by_name(template_name) if template_name else random.choice(get_all_templates())
        if not template:
            self.last_error = f"Template '{template_name}' not found"
            return None
        plan = {
            "template": template,
            "topic": topic or get_niche(),
            "tone": tone,
            "angle": "personal_story — 'I did X and learned Y'",
            "research_context": "",
        }
        return self._generate_from_plan(plan)

    def generate_from_idea(self, idea: str, variant: str = "actionable", formats: list[str] | None = None,
                           tones: list[str] | None = None, angles: list[str] | None = None,
                           structures: list[str] | None = None) -> QueuedPost | None:
        """Generate a post from a freeform idea with style controls."""
        prompt = build_idea_prompt(idea=idea, variant=variant, formats=formats, tones=tones, angles=angles,
                                   structures=structures,
                                   performance_context=self.learning_context.build_performance_context())
        raw = self._call_claude(prompt, "idea")
        if not raw:
            return None
        return create_queued_post(self.db, raw, topic=(idea or "freeform idea")[:200], source="idea",
                                  template_name=f"Idea ({variant})", generation_prompt=prompt)

    def regenerate(self, post_id: int, feedback: str = "") -> QueuedPost | None:
        """Rewrite a post using its rejection reason and optional feedback."""
        original = self.db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
        if not original:
            self.last_error = "Post not found"
            return None
        prompt = build_regeneration_prompt(original_post=original.content,
                                           template_name=original.template_name or "unknown",
                                           rejection_reason=original.rejection_reason or "", feedback=feedback)
        raw = self._call_claude(prompt, "regenerate")
        if not raw:
            return None
        return create_queued_post(self.db, raw, topic=original.topic or "", source="regenerate",
                                  template_name=original.template_name,
                                  research_context=original.research_context or "", generation_prompt=prompt,
                                  formula_id=original.formula_id, goal=original.goal)

    def generate_from_competitor(self, competitor_name: str, competitor_content: str, hook_style: str = "",
                                 content_format: str = "", topic: str = "", why_it_works: str = "",
                                 how_to_recreate: str = "", engagement_stats: str = "") -> QueuedPost | None:
        """Generate an original post inspired by a competitor's post structure."""
        prompt = build_recreate_prompt(
            competitor_name=competitor_name, competitor_content=competitor_content, hook_style=hook_style,
            content_format=content_format, topic=topic, why_it_works=why_it_works,
            how_to_recreate=how_to_recreate, engagement_stats=engagement_stats,
            performance_context=self.learning_context.build_performance_context(),
        )
        raw = self._call_claude(prompt, "competitor_recreate")
        if not raw:
            return None
        research_context = (
            f"INSPIRED BY COMPETITOR POST ({competitor_name}):\nHook style: {hook_style or 'N/A'}\n"
            f"Format: {content_format or 'N/A'}\nTopic: {topic or 'N/A'}\nEngagement: {engagement_stats}\n"
            f"Why it works: {why_it_works or 'N/A'}\nHow to recreate: {how_to_recreate or 'N/A'}\n\n"
            f"ORIGINAL POST (reference):\n{competitor_content}"
        )
        return create_queued_post(self.db, raw, topic=topic or "Competitor inspiration", source="competitor",
                                  template_name=f"Recreate ({competitor_name})", research_context=research_context,
                                  generation_prompt=prompt)

    # ── Internals ─────────────────────────────────────────────

    def _performance_context(self) -> str:
        context = self.learning_context.build_performance_context()
        if not settings.AUTORESEARCH_ENABLED:
            return context
        try:
            from autoresearch.log import ExperimentLog
            lines = [
                f"- {dim}: '{d['label']}' scores best (avg {d['avg_score']:.0f}, wins {d['win_rate']:.0f}% of experiments)"
                for dim, d in ExperimentLog(self.db).get_winning_parameters().items()
                if d["total_experiments"] >= 3
            ]
        except Exception as e:
            logger.debug("Autoresearch parameter lookup failed: %s", e)
            lines = []
        if lines:
            block = "AUTORESEARCH DATA (from automated experiments):\n" + "\n".join(lines)
            context = f"{context}\n\n{block}" if context else block
        return context

    def _hook_examples(self, topic: str) -> list[str] | None:
        if not settings.HOOK_LIBRARY_ENABLED:
            return None
        try:
            from content.hook_library import HookLibrary
            hooks = HookLibrary(self.db).get_hooks_for_topic(topic, limit=5)
            return [h.text for h in hooks] or None
        except Exception as e:
            logger.debug("Hook library lookup failed: %s", e)
            return None

    def _generate_from_plan(self, plan: dict) -> QueuedPost | None:
        """Generate one post from a content plan and queue it."""
        template = plan["template"]
        prompt = build_generation_prompt(
            template=template, topic=plan["topic"], tone=plan["tone"], angle=plan["angle"],
            research_context=plan.get("research_context", ""),
            performance_context=self._performance_context(),
            hook_examples=self._hook_examples(plan["topic"]),
        )
        raw = self._call_claude(prompt)
        if not raw:
            return None
        post = create_queued_post(
            self.db, raw, topic=plan["topic"], source=plan.get("source", "auto"), template_name=template.name,
            research_context=plan.get("research_context", ""), generation_prompt=prompt,
            research_item_id=plan.get("research_item_id"), formula_id=_formula_id(template.name),
            goal=plan.get("goal"),
        )
        self._auto_media(post, plan, template)
        return post

    def _auto_media(self, post: QueuedPost, plan: dict, template) -> None:
        """Optional GIF/image, only when text-only mode is off and the feature is enabled."""
        if settings.TEXT_ONLY_DEFAULT:
            return
        from content.content_strategy import select_media_type
        media_type = select_media_type(topic=plan["topic"], template_name=template.name, angle=plan["angle"],
                                       research_context=plan.get("research_context", ""))
        if media_type == "gif" and settings.GIF_AUTO_GENERATE:
            try:
                from content.gif_generator import GifGenerator
                from content.gif_planner import plan_gif
                gif_plan = plan_gif(post.content, plan["topic"])
                if gif_plan and gif_plan.get("gif_type") not in (None, "none"):
                    params = dict(gif_plan.get("params") or {}, gif_type=gif_plan["gif_type"])
                    GifGenerator().generate_for_post(self.db, post.id, mode="programmatic", gif_params=params)
            except Exception as e:
                logger.warning("Auto GIF generation failed for post #%s: %s", post.id, e)
        elif media_type == "image" and settings.IMAGE_AUTO_GENERATE and (settings.KIE_API_KEY or settings.GEMINI_API_KEY):
            try:
                from content.image_generator import ImageGenerator
                ImageGenerator().generate_for_post(self.db, post.id)
            except Exception as e:
                logger.warning("Auto image generation failed for post #%s: %s", post.id, e)

    def _call_claude(self, prompt: str, feature: str = "generate") -> str | None:
        """Generate post text via the shared LLM gateway (writing rules + brand in system)."""
        try:
            return llm.complete(feature, prompt, packs=("post",), instructions=WRITING_RULES).text
        except llm.LLMError as e:
            logger.error("Generation failed: %s", e)
            self.last_error = str(e)
            return None
