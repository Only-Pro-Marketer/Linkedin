"""Content generation orchestrator — uses Claude API to create LinkedIn posts."""

import json
import logging
from datetime import datetime

import anthropic
from sqlalchemy.orm import Session

from config import settings, get_anthropic_client
from content.content_strategy import ContentStrategy
from content.fact_checker import FactChecker
from content.post_formatter import format_for_linkedin, validate_length
from content.virality_scorer import ViralityScorer
from content.prompt_builder import (
    build_generation_prompt,
    build_idea_prompt,
    build_newsjack_prompt,
    build_recreate_prompt,
    build_regeneration_prompt,
)
from database.models import QueuedPost, PostStatus
from existing_tool.post_analyzer import PostAnalyzer

logger = logging.getLogger(__name__)


class ContentGenerator:
    """Generates LinkedIn posts using Claude API with templates and research."""

    def __init__(self, db: Session):
        self.db = db
        self.client = get_anthropic_client()
        self.analyzer = PostAnalyzer()
        self.strategy = ContentStrategy(db)
        self.fact_checker = FactChecker()
        self.virality_scorer = ViralityScorer()
        # Learning system: inject performance context into prompts
        from analytics.learning_context import LearningContext
        self.learning_context = LearningContext(db)

    def generate_batch(self, count: int = 5) -> list[QueuedPost]:
        """Generate a batch of posts using content strategy planning."""
        plans = self.strategy.plan_next_posts(count=count)
        posts = []

        for plan in plans:
            try:
                post = self._generate_from_plan(plan)
                if post:
                    posts.append(post)
            except Exception as e:
                logger.error("Failed to generate post: %s", e)
                continue

        logger.info("Generated %d/%d posts", len(posts), count)
        return posts

    def generate_single(
        self,
        template_name: str | None = None,
        topic: str = "",
        tone: str = "authoritative",
    ) -> QueuedPost | None:
        """Generate a single post, optionally with specific parameters."""
        from content.templates.template_library import get_template_by_name, get_all_templates

        if template_name:
            template = get_template_by_name(template_name)
        else:
            templates = get_all_templates()
            import random
            template = random.choice(templates)

        if not template:
            logger.error("Template '%s' not found", template_name)
            return None

        plan = {
            "template": template,
            "topic": topic or "supplements and health e-commerce insights",
            "tone": tone,
            "angle": "personal_story — 'I did X and learned Y'",
            "research_context": "",
        }
        return self._generate_from_plan(plan)

    def generate_from_idea(
        self,
        idea: str,
        variant: str = "actionable",
        formats: list[str] | None = None,
        tones: list[str] | None = None,
        angles: list[str] | None = None,
        structures: list[str] | None = None,
    ) -> QueuedPost | None:
        """Generate a post from a freeform idea with specific style controls."""
        performance_context = self.learning_context.build_performance_context()

        prompt = build_idea_prompt(
            idea=idea,
            variant=variant,
            formats=formats,
            tones=tones,
            angles=angles,
            structures=structures,
            performance_context=performance_context,
        )

        raw = self._call_claude(prompt)
        if not raw:
            return None

        # Derive topic from the idea (first 200 chars)
        topic = idea[:200] if idea else "freeform idea"

        content = format_for_linkedin(raw, topic)

        stats = validate_length(content)
        if not stats["valid"]:
            logger.warning("Idea post too long (%d chars), truncating", stats["char_count"])

        structure = self.analyzer.analyze(content)

        fc_result = self.fact_checker.check(
            post_content=content,
            topic=topic,
        )

        v_result = self.virality_scorer.score(
            post_content=content,
            topic=topic,
        )

        post = QueuedPost(
            content=content,
            hook=structure.hook,
            hook_type=structure.hook_type.value,
            body_format=structure.body_format.value,
            cta_type=structure.cta_type.value,
            template_name=f"Idea ({variant})",
            word_count=structure.word_count,
            status=PostStatus.QUEUED,
            topic=topic,
            generation_prompt=prompt,
            fact_check_status=fc_result["verdict"],
            fact_check_notes=json.dumps(fc_result),
            fact_checked_at=datetime.utcnow(),
            virality_score=v_result.get("total_score"),
            virality_breakdown=json.dumps(v_result),
            virality_performance=v_result.get("predicted_performance"),
        )
        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)

        logger.info(
            "Generated idea post #%s: variant=%s, score=%s/100, %d words",
            post.id,
            variant,
            v_result.get("total_score"),
            structure.word_count,
        )
        return post

    def regenerate(
        self,
        post_id: int,
        feedback: str = "",
    ) -> QueuedPost | None:
        """Regenerate a rejected/draft post with optional feedback."""
        original = self.db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
        if not original:
            logger.error("Post %s not found for regeneration", post_id)
            return None

        prompt = build_regeneration_prompt(
            original_post=original.content,
            template_name=original.template_name or "unknown",
            rejection_reason=original.rejection_reason or "",
            feedback=feedback,
        )

        raw = self._call_claude(prompt)
        if not raw:
            return None

        content = format_for_linkedin(raw, original.topic or "")

        # Analyze structure
        structure = self.analyzer.analyze(content)

        # Fact-check regenerated post
        fc_result = self.fact_checker.check(
            post_content=content,
            topic=original.topic or "",
            research_context=original.research_context or "",
        )

        # Virality scoring
        v_result = self.virality_scorer.score(
            post_content=content,
            topic=original.topic or "",
        )

        new_post = QueuedPost(
            content=content,
            hook=structure.hook,
            hook_type=structure.hook_type.value,
            body_format=structure.body_format.value,
            cta_type=structure.cta_type.value,
            template_name=original.template_name,
            word_count=structure.word_count,
            status=PostStatus.QUEUED,
            topic=original.topic,
            research_context=original.research_context,
            generation_prompt=prompt,
            fact_check_status=fc_result["verdict"],
            fact_check_notes=json.dumps(fc_result),
            fact_checked_at=datetime.utcnow(),
            virality_score=v_result.get("total_score"),
            virality_breakdown=json.dumps(v_result),
            virality_performance=v_result.get("predicted_performance"),
        )
        self.db.add(new_post)
        self.db.commit()
        self.db.refresh(new_post)

        logger.info("Regenerated post %s -> new post %s", post_id, new_post.id)
        return new_post

    def generate_from_competitor(
        self,
        competitor_name: str,
        competitor_content: str,
        hook_style: str = "",
        content_format: str = "",
        topic: str = "",
        why_it_works: str = "",
        how_to_recreate: str = "",
        engagement_stats: str = "",
    ) -> QueuedPost | None:
        """Generate an original post inspired by a competitor's viral post."""
        performance_context = self.learning_context.build_performance_context()

        prompt = build_recreate_prompt(
            competitor_name=competitor_name,
            competitor_content=competitor_content,
            hook_style=hook_style,
            content_format=content_format,
            topic=topic,
            why_it_works=why_it_works,
            how_to_recreate=how_to_recreate,
            engagement_stats=engagement_stats,
            performance_context=performance_context,
        )

        raw = self._call_claude(prompt)
        if not raw:
            return None

        content = format_for_linkedin(raw, topic or "competitor inspiration")

        stats = validate_length(content)
        if not stats["valid"]:
            logger.warning("Recreated post too long (%d chars), truncating", stats["char_count"])

        structure = self.analyzer.analyze(content)

        fc_result = self.fact_checker.check(
            post_content=content,
            topic=topic or "competitor inspiration",
        )

        v_result = self.virality_scorer.score(
            post_content=content,
            topic=topic or "competitor inspiration",
        )

        research_context = (
            f"INSPIRED BY COMPETITOR POST ({competitor_name}):\n"
            f"Hook style: {hook_style or 'N/A'}\n"
            f"Format: {content_format or 'N/A'}\n"
            f"Topic: {topic or 'N/A'}\n"
            f"Engagement: {engagement_stats}\n"
            f"Why it works: {why_it_works or 'N/A'}\n"
            f"How to recreate: {how_to_recreate or 'N/A'}\n\n"
            f"ORIGINAL POST (reference):\n{competitor_content}"
        )

        post = QueuedPost(
            content=content,
            hook=structure.hook,
            hook_type=structure.hook_type.value,
            body_format=structure.body_format.value,
            cta_type=structure.cta_type.value,
            template_name=f"Recreate ({competitor_name})",
            word_count=structure.word_count,
            status=PostStatus.QUEUED,
            topic=topic or "Competitor Inspiration",
            research_context=research_context,
            generation_prompt=prompt,
            fact_check_status=fc_result["verdict"],
            fact_check_notes=json.dumps(fc_result),
            fact_checked_at=datetime.utcnow(),
            virality_score=v_result.get("total_score"),
            virality_breakdown=json.dumps(v_result),
            virality_performance=v_result.get("predicted_performance"),
        )
        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)

        logger.info(
            "Recreated post #%s from %s: score=%s/100, %d words",
            post.id,
            competitor_name,
            v_result.get("total_score"),
            structure.word_count,
        )
        return post

    def _generate_from_plan(self, plan: dict) -> QueuedPost | None:
        """Generate a single post from a content plan."""
        template = plan["template"]

        performance_context = self.learning_context.build_performance_context()

        # Fetch autoresearch winning parameters for context
        autoresearch_lines = []
        if settings.AUTORESEARCH_ENABLED:
            try:
                from autoresearch.log import ExperimentLog
                exp_log = ExperimentLog(self.db)
                winners = exp_log.get_winning_parameters()
                for dim, data in winners.items():
                    if data["total_experiments"] >= 3:
                        autoresearch_lines.append(
                            f"- {dim}: '{data['label']}' scores best "
                            f"(avg {data['avg_score']:.0f}, wins {data['win_rate']:.0f}% of experiments)"
                        )
            except Exception as e:
                logger.debug("Autoresearch parameter lookup failed: %s", e)

        if autoresearch_lines:
            autoresearch_context = (
                "AUTORESEARCH DATA (from automated experiments):\n"
                + "\n".join(autoresearch_lines)
            )
            if performance_context:
                performance_context += "\n\n" + autoresearch_context
            else:
                performance_context = autoresearch_context

        # Fetch winning hooks for inspiration
        hook_examples = None
        if settings.HOOK_LIBRARY_ENABLED:
            try:
                from content.hook_library import HookLibrary
                hook_lib = HookLibrary(self.db)
                hooks = hook_lib.get_hooks_for_topic(plan["topic"], limit=5)
                if hooks:
                    hook_examples = [h.text for h in hooks]
                    hook_lib.mark_used([h.id for h in hooks])
            except Exception as e:
                logger.debug("Hook library lookup failed: %s", e)

        prompt = build_generation_prompt(
            template=template,
            topic=plan["topic"],
            tone=plan["tone"],
            angle=plan["angle"],
            research_context=plan.get("research_context", ""),
            performance_context=performance_context,
            hook_examples=hook_examples,
        )

        raw = self._call_claude(prompt)
        if not raw:
            return None

        # Format for LinkedIn
        content = format_for_linkedin(raw, plan["topic"])

        # Validate length
        stats = validate_length(content)
        if not stats["valid"]:
            logger.warning("Generated post too long (%d chars), truncating", stats["char_count"])

        # Analyze structure
        structure = self.analyzer.analyze(content)

        # Fact-check before queuing
        fc_result = self.fact_checker.check(
            post_content=content,
            topic=plan["topic"],
            research_context=plan.get("research_context", ""),
        )

        # Virality scoring
        v_result = self.virality_scorer.score(
            post_content=content,
            topic=plan["topic"],
        )

        # Store in queue
        post = QueuedPost(
            content=content,
            hook=structure.hook,
            hook_type=structure.hook_type.value,
            body_format=structure.body_format.value,
            cta_type=structure.cta_type.value,
            template_name=template.name,
            word_count=structure.word_count,
            status=PostStatus.QUEUED,
            topic=plan["topic"],
            research_context=plan.get("research_context", ""),
            generation_prompt=prompt,
            fact_check_status=fc_result["verdict"],
            fact_check_notes=json.dumps(fc_result),
            fact_checked_at=datetime.utcnow(),
            virality_score=v_result.get("total_score"),
            virality_breakdown=json.dumps(v_result),
            virality_performance=v_result.get("predicted_performance"),
        )
        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)

        # Auto-generate media (GIF or image) based on content strategy
        # When TEXT_ONLY_DEFAULT is True, skip all media generation
        # (text-only posts get 82 avg likes vs 5.2 for image posts)
        if not settings.TEXT_ONLY_DEFAULT:
            from content.content_strategy import select_media_type
            media_type = select_media_type(
                topic=plan["topic"],
                template_name=template.name,
                angle=plan["angle"],
                research_context=plan.get("research_context", ""),
            )
        else:
            media_type = "none"

        if media_type == "gif" and settings.GIF_AUTO_GENERATE:
            try:
                from content.gif_generator import GifGenerator
                from content.gif_planner import plan_gif
                gif_plan = plan_gif(content, plan["topic"])
                gif_gen = GifGenerator()
                if gif_plan and gif_plan.get("gif_type") and gif_plan["gif_type"] != "none":
                    planned_params = gif_plan.get("params", {})
                    planned_params["gif_type"] = gif_plan["gif_type"]
                    gif_gen.generate_for_post(
                        self.db, post.id,
                        mode="programmatic",
                        gif_params=planned_params,
                    )
                else:
                    gif_gen.generate_for_post(self.db, post.id, mode="auto")
            except Exception as e:
                logger.warning("Auto GIF generation failed for post #%s: %s — falling back to image", post.id, e)
                if settings.IMAGE_AUTO_GENERATE and settings.GEMINI_API_KEY:
                    try:
                        from content.image_generator import ImageGenerator
                        ImageGenerator().generate_for_post(self.db, post.id)
                    except Exception as img_e:
                        logger.warning("Fallback image generation also failed for post #%s: %s", post.id, img_e)
        elif settings.IMAGE_AUTO_GENERATE and settings.GEMINI_API_KEY:
            try:
                from content.image_generator import ImageGenerator
                ImageGenerator().generate_for_post(self.db, post.id)
            except Exception as e:
                logger.warning("Auto image generation failed for post #%s: %s", post.id, e)

        logger.info(
            "Generated post #%s: template=%s, hook=%s, %d words",
            post.id,
            template.name,
            structure.hook_type.value,
            structure.word_count,
        )
        return post

    def _call_claude(self, prompt: str) -> str | None:
        """Make the Claude API call and return raw text."""
        try:
            message = self.client.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=settings.CLAUDE_MAX_TOKENS,
                temperature=settings.CLAUDE_TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text.strip()
        except anthropic.APIError as e:
            logger.error("Claude API error: %s", e)
            return None
        except Exception as e:
            logger.error("Unexpected error calling Claude: %s", e)
            return None
