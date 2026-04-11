"""Build Claude API prompts from templates, research context, and brand persona."""

from pathlib import Path

from existing_tool.models import PostTemplate

# ── Load brand persona from soul/soul.md ────────────────────────
_SOUL_PATH = Path(__file__).resolve().parent.parent / "soul" / "soul.md"


def _load_soul() -> str:
    """Read soul.md and return its contents (or a fallback message)."""
    try:
        return _SOUL_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "(soul/soul.md not found — please create it from the template)"


def _build_brand_persona() -> str:
    """Build the BRAND_PERSONA prompt section from soul.md."""
    soul = _load_soul()
    return f"""You are writing a LinkedIn post for the person described below.
Read their profile carefully and adopt their voice, tone, and perspective.

--- BRAND IDENTITY (from soul.md) ---
{soul}
--- END BRAND IDENTITY ---

IMPORTANT RULES:
- Write from the perspective described in the soul file above.
- Match the voice, tone, and audience defined there.
- Use concrete numbers and specifics — never vague claims.
- Every post should feel authentic to this person's brand.
"""


BRAND_PERSONA = _build_brand_persona()

VIRALITY_RULES = """VIRALITY REQUIREMENTS — follow these strictly:

1. FIRST LINE must be a scroll-stopper (pattern interrupt). It gets 80% of the attention.
2. ONE thought per line. Every thought gets its own line.
3. Use CONCRETE numbers over vague claims ($47K not "a lot of money", 18 months not "a while").
4. Include at least one unexpected insight or contrarian angle.
5. End with an engagement driver (question, agree/disagree, share prompt).
6. Total length: 150-250 words (LinkedIn sweet spot for engagement).
7. NO corporate jargon. Write like you talk to a friend.
8. Do NOT use asterisks or markdown formatting. Plain text only.
9. Limit emoji to 0-3 per post (only where they add value, like checkmarks in lists).
10. Do NOT include any hashtags. No # symbols at all.

LINKEDIN ALGORITHM RULES (2025-2026):
11. The first 2-3 sentences MUST create enough curiosity that the reader expands the post. LinkedIn measures DWELL TIME — how long people spend reading. Write to maximize time-on-post.
12. End with an EASY-TO-ANSWER question. Posts ending with questions get 72% more comments. The question should be something anyone in the audience can answer from their own experience.
13. Write for SAVES and SENDS — include at least one framework, insight, or data point valuable enough that someone would bookmark this post or send it to a colleague.
14. Hit enter twice after your hook. The whitespace creates a visual pause that increases click-through.
15. NEVER use images unless specifically requested. Text-only posts perform 16x better for this account.

CRITICAL FORMATTING RULE:
Put a BLANK LINE between every thought/sentence. This is non-negotiable.
The ONLY exception is list items (numbered lists, bullet points, timeline entries) which stay grouped together.

CORRECT example:
I spent $47K on a marketing tool.

It completely failed.

Here's what happened:

Month 1: Revenue dropped 12%.
Month 2: Clients got confused.
Month 3: I pulled the plug.

So I tried something different.

WRONG example (lines crammed together without blank lines):
I spent $47K on a marketing tool.
It completely failed.
Here's what happened.
So I tried something different.
"""


def build_generation_prompt(
    template: PostTemplate,
    topic: str,
    tone: str,
    angle: str,
    research_context: str = "",
    performance_context: str = "",
    hook_examples: list[str] | None = None,
) -> str:
    """Build a complete Claude prompt for generating a LinkedIn post."""
    research_section = ""
    if research_context:
        research_section = f"""
TRENDING CONTEXT (use this as inspiration, NOT as a script):
{research_context}
"""

    performance_section = ""
    if performance_context:
        performance_section = f"\n{performance_context}\n"

    hooks_section = ""
    if hook_examples:
        hooks_list = "\n".join(f"- {h}" for h in hook_examples[:5])
        hooks_section = f"""
WINNING HOOKS FOR INSPIRATION (these scored highest engagement):
{hooks_list}

Study the STRUCTURE and ENERGY of these hooks, then create something ORIGINAL in the same style.
Do NOT copy them — use them to understand what makes a scroll-stopping first line.
"""

    return f"""{BRAND_PERSONA}

{VIRALITY_RULES}
{performance_section}{hooks_section}
TEMPLATE TO FOLLOW: "{template.name}"

TEMPLATE STRUCTURE:
Hook Pattern: {template.hook_pattern}
Body Pattern: {template.body_pattern}
CTA Pattern: {template.cta_pattern}

TEMPLATE INSTRUCTIONS:
{template.fill_instructions}

TOPIC: {topic}
TONE: {tone}
ANGLE: {angle}
{research_section}
WRITING INSTRUCTIONS:
1. Follow the template structure above — same hook type, body format, and CTA style.
2. Fill all [PLACEHOLDER] markers with content relevant to e-commerce growth, marketing, and the brands you serve.
3. Use a {tone} tone throughout.
4. The angle should be: {angle}
5. Make it feel authentic and personal — NOT templated or AI-generated.
6. Include specific, concrete details (real challenges, real numbers, real scenarios).
7. The hook MUST stop the scroll — it should make someone pause mid-feed.
8. Every line should earn the next line. Cut anything that doesn't pull the reader forward.

OUTPUT:
Provide ONLY the completed LinkedIn post, ready to publish. No explanations, no meta-commentary, no "here's the post:" prefix. Just the post text."""


def build_newsjack_prompt(
    news_item: dict,
    template: PostTemplate,
    tone: str = "authoritative",
    performance_context: str = "",
) -> str:
    """Build a prompt for sharing news/trends as a clean summary for LinkedIn."""
    performance_section = ""
    if performance_context:
        performance_section = f"\n{performance_context}\n"

    return f"""{BRAND_PERSONA}

{VIRALITY_RULES}
{performance_section}
NEWS/TREND TO SHARE:
Title: {news_item.get('title', '')}
Summary: {news_item.get('content', '')}
Source: {news_item.get('source', '')}

YOUR TASK:
Write a LinkedIn post that SHARES this news/trend with your audience. You are sharing news — NOT telling a personal story.

RULES FOR NEWS POSTS:
1. Open with a scroll-stopping hook about the news itself (NOT about you or your experience).
2. Summarize the key points in clear BULLET POINTS so people can scan quickly.
3. Use → or - for bullet points. Each bullet should be one key takeaway from the story.
4. Keep bullets concise — one line each, no fluff.
5. After the bullets, add 1-2 lines on why this matters for your audience (e-commerce founders, DTC brands, marketers).
6. Do NOT say "I did this" or "at my agency" or relate this to personal experience.
7. You are a news curator sharing valuable information — that's it.
8. End with a question about the news topic to drive comments.

STRUCTURE:
[Scroll-stopping hook about the news]

[Blank line]

Key takeaways:

→ [Bullet point 1]
→ [Bullet point 2]
→ [Bullet point 3]
→ [Bullet point 4] (if needed)

[Blank line]

[1-2 lines on why this matters for e-commerce/marketing professionals]

[Blank line]

[Question to drive discussion]

OUTPUT:
Provide ONLY the completed LinkedIn post. No explanations."""


def build_news_summary_prompt(
    topic: str,
    title: str,
    content: str,
    source: str = "",
    url: str = "",
) -> str:
    """Build a prompt for creating a news summary post from a research item."""
    source_line = f"\nSource: {source}" if source else ""
    url_line = f"\nURL: {url}" if url else ""

    return f"""{BRAND_PERSONA}

{VIRALITY_RULES}

NEWS/RESEARCH TO SHARE:
Topic: {topic}
Title: {title}
Content: {content}{source_line}{url_line}

YOUR TASK:
Write a LinkedIn post that SUMMARIZES this news/research for your audience. You are sharing information — NOT telling a personal story about yourself.

RULES:
1. Hook: A bold, scroll-stopping statement about the news (NOT about you).
2. Body: Summarize the key points in BULLET POINTS using → symbols.
3. Each bullet = one clear takeaway. Keep them scannable and concise.
4. Do NOT relate this to your personal experience or agency work.
5. Do NOT say "I", "my agency", "we helped", or reference any specific company.
6. You are curating and sharing — like a news anchor, not a storyteller.
7. After the bullets, add 1-2 lines on why this matters for e-commerce/marketing professionals.
8. End with a discussion question about the topic.
9. No hashtags. No emojis except where genuinely useful.
10. 150-250 words.

STRUCTURE EXAMPLE:
[Bold hook about the news]

Key takeaways:

→ [Point 1]
→ [Point 2]
→ [Point 3]
→ [Point 4]

Why this matters for e-commerce brands: [1-2 sentences]

[Discussion question]

OUTPUT:
Provide ONLY the completed LinkedIn post. No explanations, no prefixes. Just the post."""


def build_idea_prompt(
    idea: str,
    variant: str = "actionable",
    formats: list[str] | None = None,
    tones: list[str] | None = None,
    angles: list[str] | None = None,
    structures: list[str] | None = None,
    performance_context: str = "",
) -> str:
    """Build a Claude prompt to turn a raw idea into a polished LinkedIn post."""
    format_str = ", ".join(formats) if formats else "concise"
    tone_str = ", ".join(tones) if tones else "friendly"
    angle_str = ", ".join(angles) if angles else "story"
    structure_str = ", ".join(structures) if structures else "AIDA"

    variant_instructions = {
        "actionable": "Make it highly actionable — give the reader concrete steps, tactics, or a framework they can use TODAY.",
        "storytelling": "Tell a compelling story — use narrative arc, tension, and a clear lesson. Start with a moment, not a statement.",
        "thought-provoking": "Challenge conventional thinking — present a surprising insight or question that makes people pause and reconsider.",
        "contrarian": "Take a bold contrarian stance — argue against something the industry commonly believes. Be provocative but back it up.",
        "vulnerable": "Be genuinely vulnerable — share a real failure, mistake, or struggle. Show the messy behind-the-scenes.",
        "data-driven": "Lead with data and numbers — use statistics, benchmarks, results, and specifics to make your point irrefutable.",
    }

    variant_text = variant_instructions.get(variant, variant_instructions["actionable"])

    performance_section = ""
    if performance_context:
        performance_section = f"\n{performance_context}\n"

    return f"""{BRAND_PERSONA}

{VIRALITY_RULES}
{performance_section}
YOUR IDEA:
---
{idea}
---

VARIATION STYLE: {variant}
{variant_text}

FORMAT PREFERENCES: {format_str}
TONE: {tone_str}
ANGLE: {angle_str}
COPYWRITING STRUCTURE: {structure_str}

STRUCTURE GUIDE:
- AIDA = Attention, Interest, Desire, Action
- PAS = Problem, Agitation, Solution
- BAB = Before, After, Bridge
- PPP = Problem, Promise, Proof

INSTRUCTIONS:
1. Take the raw idea above and turn it into a polished, viral LinkedIn post.
2. Follow the {structure_str} copywriting structure.
3. Use a {tone_str} tone and a {angle_str} angle.
4. Format: {format_str} — adapt the post length and style accordingly.
5. The first line MUST be a scroll-stopper.
6. Make it sound like a real person sharing a real insight — NOT like AI-generated content.
7. Include specific, concrete details and numbers where appropriate.
8. End with an engagement driver (question, agree/disagree, or share prompt).

OUTPUT:
Provide ONLY the completed LinkedIn post, ready to publish. No explanations, no meta-commentary. Just the post text."""


def build_regeneration_prompt(
    original_post: str,
    template_name: str,
    rejection_reason: str = "",
    feedback: str = "",
) -> str:
    """Build a prompt to regenerate a rejected post with improvements."""
    feedback_section = ""
    if rejection_reason:
        feedback_section += f"\nREJECTION REASON: {rejection_reason}"
    if feedback:
        feedback_section += f"\nUSER FEEDBACK: {feedback}"

    return f"""{BRAND_PERSONA}

{VIRALITY_RULES}

The following LinkedIn post was generated but needs to be rewritten:

ORIGINAL POST:
---
{original_post}
---

Template used: {template_name}
{feedback_section}

INSTRUCTIONS:
1. Rewrite this post addressing the feedback above.
2. Keep the same general template structure and topic.
3. Make it significantly different from the original — don't just tweak words.
4. Ensure it follows all virality requirements.

OUTPUT:
Provide ONLY the rewritten LinkedIn post. No explanations."""


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
    """Build a prompt to create an original post inspired by a competitor's viral post."""
    analysis_section = ""
    if why_it_works:
        analysis_section += f"\nWHY THIS POST WORKED: {why_it_works}"
    if how_to_recreate:
        analysis_section += f"\nRECREATION GUIDE: {how_to_recreate}"

    performance_section = ""
    if performance_context:
        performance_section = f"\n{performance_context}\n"

    return f"""{BRAND_PERSONA}

{VIRALITY_RULES}
{performance_section}
You are creating an ORIGINAL LinkedIn post inspired by a high-performing competitor post.

COMPETITOR POST ({competitor_name}):
---
{competitor_content}
---

COMPETITOR POST ANALYSIS:
- Hook style: {hook_style or 'N/A'}
- Content format: {content_format or 'N/A'}
- Topic area: {topic or 'N/A'}
- Engagement: {engagement_stats or 'N/A'}
{analysis_section}

INSTRUCTIONS:
1. Study the competitor post's STRUCTURE and STYLE — what makes it engaging.
2. Create a COMPLETELY ORIGINAL post on the same topic area but from YOUR perspective as an agency owner.
3. Use the same hook style ({hook_style or 'bold statement'}) and content format ({content_format or 'list'}).
4. Draw from YOUR experience helping e-commerce brands — use different examples, numbers, and stories.
5. Do NOT copy any specific phrases, sentences, or examples from the competitor post.
6. Match or exceed the engagement potential by applying what made their post work.
7. Make it feel authentic — like YOU wrote it from your real agency experience.
8. Include specific numbers and concrete details from your perspective.

OUTPUT:
Provide ONLY the completed LinkedIn post, ready to publish. No explanations, no meta-commentary. Just the post text."""
