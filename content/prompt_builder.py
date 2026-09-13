"""Prompts for post generation.

The brand voice and the writing rules live in the cached system prompt (see
llm.system_blocks); the functions here only build the per-request user message.
Third-party text (research, competitor posts) is wrapped with llm.untrusted().
"""

from content.brand import get_niche
from existing_tool.models import PostTemplate
from llm import untrusted

# Sent as system instructions for every post-writing call. Merges the engine's
# original rules with the 2026 findings from the linkedin-skills research.
WRITING_RULES = """LINKEDIN WRITING RULES — follow them in every post:

HOOK
1. The first line is a statement or a specific number with a referent ("$4,730 in March ad spend", not "a lot of money"). Never open with a question, "Here's what/how…", "Stop X, start Y", "In today's…" or an announcement ("I'm excited to share").
2. The hook must land within the first ~140 characters, before LinkedIn's "…see more".

SHAPE
3. 150–250 words (about 900–1,500 characters). Plain text only: no markdown, no asterisks, no hashtags, no links in the body (links go in the first comment).
4. One or two sentences per paragraph, with a blank line between paragraphs. Keep the whole post under 22 line breaks — LinkedIn cuts posts after about 25. Short list items may sit on consecutive lines.
5. One contrast and at most one list of three per post. No reveal bridges ("The result?", "Plot twist:", "Here's the thing"), no "It's not X, it's Y", no staccato runs ("Short. Punchy. Done."), no one-word paragraphs.

VOICE
6. Specific beats vague: real numbers with context, named tools, places and dates. But never present invented numbers or client stories as real — use only facts from the brand profile or the request, or make it clearly hypothetical.
7. Avoid AI vocabulary: leverage, streamline, harness, delve, unlock, foster, elevate, empower, robust, seamless, landscape, crucial, significant, notably, game-changer, deep dive. Use at most one em dash; prefer commas or colons.
8. No sincerity announcements ("let me be honest", "real talk", "unpopular opinion"). State an uncomfortable fact plainly instead.
9. 0–2 emoji, never at the start of every line.

CLOSE
10. End with one specific question that anyone in the audience can answer from their own experience. Never "Thoughts?", "Agree?", "Agree or disagree?" or "What do you think?". A one-line P.S. is fine when there is a real follow-up.

FORMAT EXAMPLE (layout only):
I paid $47K for a marketing tool we cancelled after 90 days.

Month one, revenue dipped 12% while the team learned it.

By month three, clients were confused by the new reports, so we pulled the plug.

What we kept was the one habit it forced on us: a weekly 20-minute numbers review.

Which tool did you cancel last year, and what did it teach you?"""

# Backwards-compatible alias (older modules import VIRALITY_RULES).
VIRALITY_RULES = WRITING_RULES

OUTPUT_ONLY = "Output only the finished post text — no title, no explanation, no quotation marks."


def _section(title: str, body: str) -> str:
    return f"\n{title}\n{body}\n" if body else ""


def build_generation_prompt(
    template: PostTemplate,
    topic: str,
    tone: str,
    angle: str,
    research_context: str = "",
    performance_context: str = "",
    hook_examples: list[str] | None = None,
) -> str:
    """User message for generating one post from a template."""
    hooks = ""
    if hook_examples:
        hooks = "\n".join(f"- {h}" for h in hook_examples[:5])
        hooks += "\nStudy their structure and energy; write something original. Do not copy them."

    research = untrusted(research_context, "research") if research_context else ""

    return f"""Write one LinkedIn post.

TEMPLATE: "{template.name}"
Hook pattern: {template.hook_pattern}
Body pattern: {template.body_pattern}
CTA pattern: {template.cta_pattern}
Template notes: {template.fill_instructions}

TOPIC: {topic}
TONE: {tone}
ANGLE: {angle}
{_section("WHAT HAS WORKED FOR THIS ACCOUNT:", performance_context)}{_section("WINNING HOOKS FROM PAST POSTS (inspiration only):", hooks)}{_section("TRENDING CONTEXT (inspiration, not a script):", research)}
INSTRUCTIONS:
1. Follow the template's structure. When the template conflicts with the writing rules, the writing rules win.
2. Replace any [PLACEHOLDER] with specifics from the brand profile or the topic — never with invented results presented as real.
3. Use a {tone} tone and this angle: {angle}.
4. It must read like the person in the brand profile wrote it, not like AI.

{OUTPUT_ONLY}"""


def build_news_summary_prompt(topic: str, title: str, content: str, source: str = "", url: str = "") -> str:
    """User message for a curated news-summary post from a research item."""
    item = f"Topic: {topic}\nTitle: {title}\nSource: {source}\nURL: {url}\n\n{content}"
    return f"""Write a LinkedIn post that shares this news with the audience in the brand profile.

{untrusted(item, "news")}

RULES FOR THIS POST:
1. Open with a plain statement of what happened (not about the author).
2. Give 3–4 key takeaways as short lines starting with "→".
3. Add 1–2 sentences on why it matters for {get_niche()}.
4. You are curating news: no "I", no "my agency", no invented experiences.
5. Close with a specific question about the news. Do not include the URL in the body.

{OUTPUT_ONLY}"""


IDEA_VARIANTS = {
    "actionable": "Make it actionable: give concrete steps, tactics or a framework the reader can use today.",
    "storytelling": "Tell a story: start at a specific moment, build tension, land one clear lesson.",
    "thought-provoking": "Challenge conventional thinking with one surprising, well-argued insight.",
    "contrarian": "Take a contrarian stance against a common industry belief, and back it up.",
    "vulnerable": "Share a real mistake or struggle, stated plainly, and what changed after it.",
    "data-driven": "Lead with data: numbers, benchmarks and results that make the point hard to argue with.",
}


def build_idea_prompt(
    idea: str,
    variant: str = "actionable",
    formats: list[str] | None = None,
    tones: list[str] | None = None,
    angles: list[str] | None = None,
    structures: list[str] | None = None,
    performance_context: str = "",
) -> str:
    """User message turning a raw idea into a post."""
    structure_str = ", ".join(structures) if structures else "AIDA"
    return f"""Turn this idea into one LinkedIn post.

IDEA:
{idea}

VARIATION: {variant} — {IDEA_VARIANTS.get(variant, IDEA_VARIANTS["actionable"])}
FORMAT: {", ".join(formats) if formats else "concise"}
TONE: {", ".join(tones) if tones else "friendly"}
ANGLE: {", ".join(angles) if angles else "story"}
COPY STRUCTURE: {structure_str} (AIDA = attention, interest, desire, action; PAS = problem, agitation, solution; BAB = before, after, bridge; PPP = problem, promise, proof)
{_section("WHAT HAS WORKED FOR THIS ACCOUNT:", performance_context)}
{OUTPUT_ONLY}"""


def build_regeneration_prompt(original_post: str, template_name: str, rejection_reason: str = "", feedback: str = "") -> str:
    """User message to rewrite a rejected post."""
    notes = ""
    if rejection_reason:
        notes += f"\nWhy it was rejected: {rejection_reason}"
    if feedback:
        notes += f"\nUser feedback: {feedback}"
    return f"""Rewrite this LinkedIn post so it is clearly better and noticeably different (not a light edit).

ORIGINAL POST (template: {template_name}):
---
{original_post}
---
{notes}

Keep the topic and general structure unless the feedback says otherwise.

{OUTPUT_ONLY}"""


def build_recreate_prompt(
    competitor_name: str,
    competitor_content: str,
    hook_style: str = "",
    content_format: str = "",
    topic: str = "",
    why_it_works: str = "",
    how_to_recreate: str = "",
    engagement_stats: str = "",
    performance_context: str = "",
) -> str:
    """User message for an original post inspired by a competitor's post."""
    analysis = (f"Hook style: {hook_style or 'n/a'}\nFormat: {content_format or 'n/a'}\nTopic: {topic or 'n/a'}\n"
                f"Engagement: {engagement_stats or 'n/a'}\nWhy it worked: {why_it_works or 'n/a'}\n"
                f"Recreation notes: {how_to_recreate or 'n/a'}")
    return f"""Write an ORIGINAL LinkedIn post inspired by the structure of a high-performing post by {competitor_name}.

{untrusted(competitor_content, "competitor_post")}

ANALYSIS OF WHY IT WORKED:
{analysis}
{_section("WHAT HAS WORKED FOR THIS ACCOUNT:", performance_context)}
INSTRUCTIONS:
1. Borrow the hook style and structure, not the words: do not reuse any phrase, example or number from that post.
2. Write from the brand profile's own perspective and niche ({get_niche()}).
3. Use only real details from the brand profile; otherwise keep examples clearly general.

{OUTPUT_ONLY}"""
