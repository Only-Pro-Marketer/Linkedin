"""AI-powered GIF planning — Claude picks the best GIF type and parameters for a post."""

import logging

import llm

logger = logging.getLogger(__name__)

GIF_PLANNING_PROMPT = """Decide the best animated GIF to accompany this LinkedIn post. The GIF must directly reinforce the post's actual content.

Available GIF types:
1. "data_counter" — a number counting up. Params: metric (str), from_val (number), to_val (number), unit ("%", "$", "x" or custom), title (str). Only if the post states a specific number; use its exact value.
2. "before_after" — two alternating frames. Params: before_text (max 4 lines separated by \\n), after_text (max 4 lines), metric_label (str), title (str). Use the before/after states the post describes.
3. "text_reveal" — lines appearing one by one. Params: lines (3–7 strings, max 40 chars each, taken from the post), title (str).
4. "stat_cards" — 3–4 metric cards. Params: stats (list of {{"label","value","change"}}), title (str). Only if the post has 3+ explicit metrics.
5. "none" — no GIF (personal stories, opinion pieces, posts without data or steps).

Rules: never invent or estimate numbers; the title summarises the post's main point.

Respond with only a JSON object: {{"gif_type": "...", "rationale": "one sentence", "params": {{...}}}}

POST TOPIC: {topic}

POST:
{content}
"""


def plan_gif(post_content: str, topic: str = "") -> dict | None:
    """Return {gif_type, rationale, params} or None on failure."""
    prompt = GIF_PLANNING_PROMPT.format(topic=topic or "not specified", content=post_content[:1500])
    try:
        plan = llm.complete_json_loose("gif_plan", prompt, brand=False, effort="low", max_tokens=3000)
    except llm.LLMError as e:
        logger.error("GIF planning failed: %s", e)
        return None
    if "gif_type" not in plan:
        logger.warning("GIF plan missing gif_type: %s", plan)
        return None
    logger.info("GIF plan: type=%s", plan["gif_type"])
    return plan
