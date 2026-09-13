"""Autoresearch experiment runner — Karpathy-style autonomous experimentation.

Generates N variations of a post varying one dimension at a time,
scores each with the virality scorer, picks the winner, queues it.
"""

import json
import logging
import random
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

import llm
from config import settings
from content.post_formatter import format_for_linkedin, validate_length
from content.prompt_builder import WRITING_RULES, build_generation_prompt
from content.templates.template_library import get_all_templates, get_template_by_name
from content.virality_scorer import ViralityScorer
from database.models import (
    Experiment,
    ExperimentType,
    ExperimentVariation,
    PostStatus,
    QueuedPost,
    ResearchItem,
)
from existing_tool.post_analyzer import PostAnalyzer

logger = logging.getLogger(__name__)

PROGRAM_PATH = Path(__file__).resolve().parent / "program.md"

# Experiment dimension definitions
# Question openers are excluded: 2026 reach data shows they underperform.
HOOK_STYLES = [
    ("contrarian", "Start with a contrarian statement that challenges conventional wisdom."),
    ("bold_statement", "Start with a bold, definitive statement that demands attention."),
    ("story_opener", "Start with a personal story opening — a specific moment in time."),
    ("statistic", "Start with a surprising statistic or data point."),
    ("personal_failure", "Start with a personal failure or mistake admission."),
]

TONES = ["authoritative", "conversational", "provocative", "vulnerable", "data-driven"]

WORD_COUNT_TARGETS = [
    ("150", "Keep it very concise — around 150 words. Every word must earn its place."),
    ("180", "Target around 180 words — punchy but with room for depth."),
    ("200", "Target around 200 words — the LinkedIn sweet spot."),
    ("220", "Target around 220 words — enough for a solid framework or story."),
    ("250", "Target around 250 words — use the extra space for concrete examples."),
]

ANGLES = [
    "personal_story — 'I did X and learned Y'",
    "data_insight — 'The numbers show X'",
    "contrarian_take — 'Everyone thinks X, but actually Y'",
    "how_to — 'Here is exactly how to do X step by step'",
    "case_study — 'Brand X did Y and got Z results'",
]


class ExperimentRunner:
    """Runs autonomous experiments to find optimal post generation parameters."""

    def __init__(self, db: Session):
        self.db = db
        self.scorer = ViralityScorer()
        self.analyzer = PostAnalyzer()

    def blocked_reason(self) -> str | None:
        """Why experiments can't run yet (off, or not enough real posts), or None."""
        from database.models import PostStatus, QueuedPost

        if not settings.AUTORESEARCH_ENABLED:
            return "Autoresearch is turned off in Settings."
        posted = self.db.query(QueuedPost).filter(QueuedPost.status == PostStatus.POSTED).count()
        if posted < settings.AUTORESEARCH_MIN_POSTED:
            return (f"Autoresearch starts after {settings.AUTORESEARCH_MIN_POSTED} published posts "
                    f"(you have {posted}). Until then it could only learn from Claude's own guesses.")
        return None

    def run_experiment_cycle(self) -> list[dict]:
        """Run a full experiment cycle — multiple experiments per cycle.

        Returns list of experiment result dicts.
        """
        reason = self.blocked_reason()
        if reason:
            logger.info("Autoresearch skipped: %s", reason)
            return []

        program = self._read_program()
        hypotheses = self._parse_hypotheses(program)
        results = []

        # Pick topics for experiments
        topics = self._pick_topics(settings.AUTORESEARCH_EXPERIMENTS_PER_CYCLE)

        for i in range(settings.AUTORESEARCH_EXPERIMENTS_PER_CYCLE):
            topic, research_context = topics[i] if i < len(topics) else (self._fallback_topic(), "")

            # Decide experiment type: rotate through types, or use hypothesis
            if i < len(hypotheses):
                exp_type, dimension_values = self._hypothesis_to_experiment(hypotheses[i])
                hypothesis_text = hypotheses[i]
            else:
                exp_type = random.choice(list(ExperimentType))
                dimension_values = self._get_dimension_values(exp_type)
                hypothesis_text = f"Exploratory: testing {exp_type.value} variations"

            try:
                result = self._run_single_experiment(
                    experiment_type=exp_type,
                    topic=topic,
                    research_context=research_context,
                    hypothesis=hypothesis_text,
                    dimension_values=dimension_values,
                )
                results.append(result)
                logger.info(
                    "Experiment #%d: type=%s, winner=%s (score=%d, spread=%d)",
                    result["experiment_id"], exp_type.value,
                    result["winner_label"], result["winner_score"], result["score_spread"],
                )
            except Exception as e:
                logger.error("Experiment %d failed: %s", i + 1, e)
                continue

        # Update program.md with results
        if results:
            self._update_program(results)

        return results

    def _run_single_experiment(
        self,
        experiment_type: ExperimentType,
        topic: str,
        research_context: str,
        hypothesis: str,
        dimension_values: list[tuple[str, str]],
    ) -> dict:
        """Run one experiment: generate variations, score, pick winner, queue.

        dimension_values: list of (label, instruction_override) tuples.
        """
        n = min(settings.AUTORESEARCH_VARIATIONS_PER_EXPERIMENT, len(dimension_values))
        selected = random.sample(dimension_values, n) if len(dimension_values) > n else dimension_values

        # Create experiment record
        experiment = Experiment(
            experiment_type=experiment_type,
            topic=topic,
            hypothesis=hypothesis,
            dimension_tested=experiment_type.value,
            variations_count=len(selected),
        )
        self.db.add(experiment)
        self.db.commit()
        self.db.refresh(experiment)

        # Pick a base template and tone (held constant unless that's the dimension being tested)
        base_template = self._pick_base_template(experiment_type)
        base_tone = "authoritative" if experiment_type == ExperimentType.TONE else random.choice(TONES)
        base_angle = random.choice(ANGLES)

        variations = []
        for label, override_instruction in selected:
            try:
                content, prompt = self._generate_variation(
                    experiment_type=experiment_type,
                    topic=topic,
                    research_context=research_context,
                    template=base_template,
                    tone=base_tone if experiment_type != ExperimentType.TONE else label,
                    angle=base_angle if experiment_type != ExperimentType.ANGLE else override_instruction,
                    override_instruction=override_instruction,
                    label=label,
                )

                if not content:
                    continue

                # Score
                v_result = self.scorer.score(content, topic)
                score = v_result.get("total_score", 0)

                # Analyze structure
                structure = self.analyzer.analyze(content)

                variation = ExperimentVariation(
                    experiment_id=experiment.id,
                    variation_label=label,
                    parameter_value=label,
                    content=content,
                    virality_score=score,
                    virality_breakdown=json.dumps(v_result),
                    hook_type=structure.hook_type.value,
                    template_name=base_template.name,
                    tone=base_tone if experiment_type != ExperimentType.TONE else label,
                    word_count=structure.word_count,
                )
                self.db.add(variation)
                variations.append(variation)

            except Exception as e:
                logger.error("Variation '%s' failed: %s", label, e)
                continue

        self.db.commit()
        for v in variations:
            self.db.refresh(v)

        if not variations:
            raise ValueError("All variations failed to generate")

        # Pick winner
        winner = max(variations, key=lambda v: v.virality_score or 0)
        winner.is_winner = True

        scores = [v.virality_score or 0 for v in variations]
        experiment.winner_variation_id = winner.id
        experiment.winner_score = winner.virality_score
        experiment.score_spread = max(scores) - min(scores)

        # Queue the winner if it meets the threshold
        queued_post = None
        if (winner.virality_score or 0) >= settings.AUTORESEARCH_MIN_SCORE_TO_QUEUE:
            from content.pipeline import create_queued_post

            queued_post = create_queued_post(
                self.db, winner.content, topic=topic, source="experiment",
                template_name=winner.template_name,
                research_context=f"[AUTORESEARCH] Experiment #{experiment.id}: {hypothesis}",
                review=False,  # already scored during the experiment
                virality=json.loads(winner.virality_breakdown or "{}") or None,
            )
            experiment.queued_post_id = queued_post.id

        self.db.commit()

        return {
            "experiment_id": experiment.id,
            "type": experiment_type.value,
            "topic": topic,
            "hypothesis": hypothesis,
            "winner_label": winner.variation_label,
            "winner_score": winner.virality_score or 0,
            "score_spread": experiment.score_spread,
            "variations": [
                {"label": v.variation_label, "score": v.virality_score, "word_count": v.word_count}
                for v in variations
            ],
            "queued_post_id": queued_post.id if queued_post else None,
        }

    def _generate_variation(
        self,
        experiment_type: ExperimentType,
        topic: str,
        research_context: str,
        template,
        tone: str,
        angle: str,
        override_instruction: str,
        label: str,
    ) -> tuple[str | None, str]:
        """Generate one variation with the specified override."""
        # Build prompt with experiment-specific override
        from analytics.learning_context import LearningContext
        learning = LearningContext(self.db)
        performance_context = learning.build_performance_context()

        # For hook experiments, inject hook style instruction
        experiment_instruction = ""
        if experiment_type == ExperimentType.HOOK:
            experiment_instruction = f"\nEXPERIMENT INSTRUCTION: {override_instruction}\n"
        elif experiment_type == ExperimentType.LENGTH:
            experiment_instruction = f"\nEXPERIMENT INSTRUCTION: {override_instruction}\n"
        elif experiment_type == ExperimentType.TEMPLATE:
            # Template is already varied via the template parameter
            pass
        # Tone and angle are varied via their parameters

        prompt = build_generation_prompt(
            template=template,
            topic=topic,
            tone=tone,
            angle=angle,
            research_context=research_context,
            performance_context=performance_context,
        )

        # Insert the experiment instruction before the task instructions
        if experiment_instruction:
            prompt = prompt.replace("INSTRUCTIONS:", f"{experiment_instruction}\nINSTRUCTIONS:", 1)

        try:
            raw = llm.complete("autoresearch", prompt, packs=("post",), instructions=WRITING_RULES).text
            return format_for_linkedin(raw, topic), prompt
        except llm.LLMError as e:
            logger.error("Variation '%s' failed: %s", label, e)
            return None, prompt

    def _pick_topics(self, count: int) -> list[tuple[str, str]]:
        """Pick topics from unused research items."""
        items = (
            self.db.query(ResearchItem)
            .filter(ResearchItem.used == False)
            .order_by(ResearchItem.relevance_score.desc())
            .limit(count)
            .all()
        )
        topics = []
        for item in items:
            topics.append((
                item.topic,
                f"Source: {item.source}\nTitle: {item.title}\n{(item.content or '')[:500]}",
            ))
        # Pad with fallback topics if needed
        fallback_topics = [
            "CRO and conversion optimization tactics from client work",
            "email and SMS marketing strategies (Klaviyo flows, campaigns, revenue)",
            "agency lessons and founder stories",
            "paid ads and media buying (Meta, TikTok, scaling spend, ROAS)",
            "Shopify development and tech stack optimization",
        ]
        while len(topics) < count:
            topics.append((random.choice(fallback_topics), ""))
        return topics

    def _fallback_topic(self) -> str:
        return random.choice([
            "CRO and conversion optimization tactics from client work",
            "email and SMS marketing strategies (Klaviyo flows, campaigns, revenue)",
            "agency lessons and founder stories",
        ])

    def _pick_base_template(self, experiment_type: ExperimentType):
        """Pick a template — random if not testing templates."""
        templates = get_all_templates()
        if experiment_type == ExperimentType.TEMPLATE:
            return templates[0]  # will be overridden per variation
        return random.choice(templates)

    def _get_dimension_values(self, exp_type: ExperimentType) -> list[tuple[str, str]]:
        """Get the parameter values to test for a given experiment type."""
        if exp_type == ExperimentType.HOOK:
            return HOOK_STYLES
        elif exp_type == ExperimentType.TONE:
            return [(t, t) for t in TONES]
        elif exp_type == ExperimentType.TEMPLATE:
            templates = get_all_templates()
            return [(t.name, t.name) for t in templates]
        elif exp_type == ExperimentType.LENGTH:
            return WORD_COUNT_TARGETS
        elif exp_type == ExperimentType.ANGLE:
            return [(a.split("—")[0].strip(), a) for a in ANGLES]
        return HOOK_STYLES  # fallback

    def _hypothesis_to_experiment(self, hypothesis: str) -> tuple[ExperimentType, list[tuple[str, str]]]:
        """Parse a hypothesis string into an experiment type and values to test."""
        h = hypothesis.lower()
        if "hook" in h:
            return ExperimentType.HOOK, HOOK_STYLES
        elif "tone" in h:
            return ExperimentType.TONE, [(t, t) for t in TONES]
        elif "template" in h:
            templates = get_all_templates()
            return ExperimentType.TEMPLATE, [(t.name, t.name) for t in templates]
        elif "word" in h or "length" in h:
            return ExperimentType.LENGTH, WORD_COUNT_TARGETS
        elif "angle" in h:
            return ExperimentType.ANGLE, [(a.split("—")[0].strip(), a) for a in ANGLES]
        # Default: hook experiment
        return ExperimentType.HOOK, HOOK_STYLES

    def _read_program(self) -> str:
        """Read program.md."""
        if PROGRAM_PATH.exists():
            return PROGRAM_PATH.read_text()
        return ""

    def _parse_hypotheses(self, program: str) -> list[str]:
        """Extract numbered hypotheses from program.md."""
        hypotheses = []
        in_section = False
        for line in program.split("\n"):
            if "## Current Hypotheses" in line:
                in_section = True
                continue
            if in_section:
                if line.startswith("## "):
                    break
                match = re.match(r"^\d+\.\s+(.+)", line.strip())
                if match:
                    hypotheses.append(match.group(1))
        return hypotheses

    def _update_program(self, results: list[dict]):
        """Append experiment results to program.md."""
        if not PROGRAM_PATH.exists():
            return

        content = PROGRAM_PATH.read_text()

        # Find the completed experiments table and append rows
        new_rows = []
        for r in results:
            new_rows.append(
                f"| {r['experiment_id']} | {r['type']} | {r['topic'][:40]} | "
                f"{r['winner_label']} | {r['winner_score']} | {r['score_spread']} | "
                f"{datetime.utcnow().strftime('%Y-%m-%d')} |"
            )

        # Insert after the table header
        marker = "| # | Type | Topic | Winner | Score | Spread | Date |"
        separator = "|---|------|-------|--------|-------|--------|------|"
        if marker in content:
            insert_pos = content.index(separator) + len(separator)
            content = content[:insert_pos] + "\n" + "\n".join(new_rows) + content[insert_pos:]
            PROGRAM_PATH.write_text(content)

    @staticmethod
    def _score_to_tier(score: int | None) -> str:
        if not score:
            return "low"
        if score >= 85:
            return "viral"
        if score >= 65:
            return "high"
        if score >= 40:
            return "medium"
        return "low"
