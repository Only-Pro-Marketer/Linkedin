"""AI-powered GIF planning — uses Claude to decide the best GIF type and parameters for a post."""

import json
import logging

import anthropic

from config import settings, get_anthropic_client

logger = logging.getLogger(__name__)

GIF_PLANNING_PROMPT = """You are a LinkedIn content strategist specializing in visual media.

Given a LinkedIn post's text content and topic, decide the best type of animated GIF to accompany it.
The GIF MUST directly relate to and reinforce the post's actual content.

Available GIF types:
1. "data_counter" — Animated number counting up. Best for: posts that mention specific metrics, growth numbers, or percentage improvements.
   Required params: metric (str), from_val (float), to_val (float), unit (str: "%", "$", "x", or custom), title (str)
   ONLY use if the post contains a specific number or metric. Extract the EXACT values from the post.

2. "before_after" — Two frames alternating. Best for: posts about transformations, redesigns, strategy pivots, or comparing old vs new approaches.
   Required params: before_text (str, max 4 lines separated by \\n), after_text (str, max 4 lines separated by \\n), metric_label (str), title (str)
   Extract the actual before/after states described in the post.

3. "text_reveal" — Lines appearing one by one. Best for: posts with tips, frameworks, step-by-step advice, listicles, or key takeaways.
   Required params: lines (list of 3-7 short strings, max 40 chars each), title (str)
   Extract the ACTUAL tips/steps/points from the post. Do not rephrase — use the post's own words, shortened to fit.

4. "stat_cards" — 3-4 metric cards appearing. Best for: posts with multiple data points, case study results, or multi-metric comparisons.
   Required params: stats (list of dicts with "label", "value", "change"), title (str)
   ONLY use if the post contains 3+ specific metrics. Extract EXACT values from the post.

5. "screen_record" — Record a website browsing. Best for: store reviews, UX demos, tool walkthroughs.
   Required params: target_url (str), focus (str describing what to show)
   ONLY use if the post references a specific, publicly accessible URL.

6. "none" — No GIF needed. Best for: personal stories, vulnerable posts, opinion pieces, or posts without clear data/steps.

CRITICAL RULES:
- The GIF must DIRECTLY reflect the post content — never create a GIF about something the post doesn't discuss
- NEVER invent, fabricate, or estimate numbers. Only use data_counter or stat_cards if the post contains EXPLICIT numbers
- If the post says "boosted conversions by 47%" → use exactly 47%, not a made-up range
- If the post has tips/steps/lessons → use text_reveal with the ACTUAL tips from the post (shortened if needed)
- If the post describes a transformation without specific numbers → use before_after with the actual concepts discussed
- If no clear data, steps, or transformation exists → prefer "text_reveal" with key sentences from the post, or "none"
- The GIF title should be a short summary of the post's main point (not generic like "THE RESULT")
- For text_reveal: extract the core message lines directly from the post body — keep them verbatim but trimmed to 40 chars max
- For before_after: the before/after text must describe what the POST actually discusses, not a generic placeholder

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "gif_type": "one of the types above",
  "rationale": "one sentence explaining how this GIF reinforces the specific post content",
  "params": {{ ... type-specific parameters extracted from the post ... }}
}}

POST TOPIC: {topic}

POST CONTENT:
{content}
"""


def plan_gif(post_content: str, topic: str = "") -> dict | None:
    """Use Claude to plan the best GIF type and parameters for a post.

    Returns dict with gif_type, rationale, and params, or None on failure.
    """
    prompt = GIF_PLANNING_PROMPT.format(
        topic=topic or "e-commerce / marketing",
        content=post_content[:1500],
    )

    try:
        client = get_anthropic_client()
        message = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=800,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Parse JSON (handle potential markdown wrapping)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        plan = json.loads(raw)

        if "gif_type" not in plan:
            logger.warning("GIF plan missing gif_type: %s", raw)
            return None

        logger.info("GIF plan: type=%s, rationale=%s", plan["gif_type"], plan.get("rationale", ""))
        return plan

    except json.JSONDecodeError as e:
        logger.error("Failed to parse GIF plan JSON: %s — raw: %s", e, raw[:200])
        return None
    except anthropic.APIError as e:
        logger.error("Claude API error in GIF planning: %s", e)
        return None
    except Exception as e:
        logger.error("GIF planning failed: %s", e)
        return None
