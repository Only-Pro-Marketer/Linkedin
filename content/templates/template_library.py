"""Template library — loads and manages all post templates."""

import json
from pathlib import Path

from existing_tool.models import PostTemplate
from existing_tool.template_extractor import TemplateExtractor

# All 20+ template definitions from the existing tool's TEMPLATE_NAMES mapping
TEMPLATE_DEFINITIONS = TemplateExtractor.TEMPLATE_NAMES

# Directory where template JSON files live
TEMPLATES_DIR = Path(__file__).parent


def load_saved_templates() -> list[PostTemplate]:
    """Load pre-extracted templates from JSON files."""
    templates = []
    for file in TEMPLATES_DIR.glob("*.json"):
        try:
            data = json.loads(file.read_text())
            templates.append(
                PostTemplate(
                    name=data["name"],
                    hook_pattern=data["hook_pattern"],
                    body_pattern=data["body_pattern"],
                    cta_pattern=data["cta_pattern"],
                    example_post=data.get("example_post", ""),
                    fill_instructions=data.get("fill_instructions", ""),
                )
            )
        except (json.JSONDecodeError, KeyError):
            continue
    return templates


# Built-in templates with fill instructions for common viral formats
BUILTIN_TEMPLATES = [
    PostTemplate(
        name="The Expensive Lesson",
        hook_pattern="I lost [DOLLAR_AMOUNT] on [SPECIFIC_THING].",
        body_pattern=(
            "Here's the brutal truth nobody told me:\n\n"
            "1. [MISTAKE_1]\n2. [MISTAKE_2]\n3. [MISTAKE_3]\n"
            "4. [MISTAKE_4]\n5. [MISTAKE_5]\n\n"
            "It took me [TIME_PERIOD] to recover.\n\n"
            "But that failure taught me more than any course ever could.\n\n"
            "Now I [CURRENT_SUCCESS_STATE].\n\n"
            "The difference? [KEY_INSIGHT]."
        ),
        cta_pattern="What's the most expensive lesson your brand taught you?",
        example_post="",
        fill_instructions=(
            "HOOK: Open with a vulnerable admission of failure with a specific dollar amount.\n"
            "BODY: List 3-5 specific mistakes, then reveal the recovery and lesson.\n"
            "CTA: End with a question inviting others to share their own failure.\n"
            "FORMAT: Use line breaks. Target ~150 words."
        ),
    ),
    PostTemplate(
        name="The Contrarian Take",
        hook_pattern="Everyone says [COMMON_BELIEF].\n\nThey're wrong.",
        body_pattern=(
            "The most [SUPERLATIVE] [SUBJECT] I've seen?\n\n"
            "They [CONTRARIAN_ACTION].\n\n"
            "Here's why:\n\n"
            "→ [REASON_1]\n→ [REASON_2]\n→ [REASON_3]\n"
            "→ [REASON_4]\n→ [REASON_5]\n\n"
            "[PROOF_POINT].\n\n"
            "Stop [BAD_ACTION]. Start [GOOD_ACTION]."
        ),
        cta_pattern="Agree or disagree?",
        example_post="",
        fill_instructions=(
            "HOOK: State what everyone believes, then signal disagreement.\n"
            "BODY: Present 5 arrow-pointed reasons why the contrarian view is correct.\n"
            "CTA: End with 'Agree or disagree?' to drive comments.\n"
            "FORMAT: Use line breaks. Target ~150 words."
        ),
    ),
    PostTemplate(
        name="The Origin Story",
        hook_pattern="I spent [TIME_PERIOD] building the \"perfect\" [PRODUCT].\n\nThen [TURNING_POINT].",
        body_pattern=(
            "[METRIC_PROGRESSION_EARLY]\n\n"
            "So I did something different.\n\n"
            "[UNCONVENTIONAL_ACTION]\n\n"
            "[METRIC_PROGRESSION_LATER]\n\n"
            "The [THING] didn't change. The [KEY_VARIABLE] did.\n\n"
            "Stop perfecting your [THING].\nStart perfecting your [KEY_VARIABLE]."
        ),
        cta_pattern="What [KEY_VARIABLE] drives most of your [OUTCOME]?",
        example_post="",
        fill_instructions=(
            "HOOK: Start with time spent on something, then a turning point.\n"
            "BODY: Show metric progression (bad -> good) with a clear pivot moment.\n"
            "CTA: Ask about their experience with the key variable.\n"
            "FORMAT: Use specific numbers (Week 1: X, Month 4: Y). Target ~200 words."
        ),
    ),
    PostTemplate(
        name="The Framework Post",
        hook_pattern="[TIME_PERIOD] ago I was [BAD_STATE].\n\nToday I [GOOD_STATE].\n\nHere's exactly what I did (step by step):",
        body_pattern=(
            "Month 1-3: [PHASE_1_NAME]\n"
            "- [ACTION_1]\n- [ACTION_2]\n- [ACTION_3]\n\n"
            "Month 4-6: [PHASE_2_NAME]\n"
            "- [ACTION_4]\n- [ACTION_5]\n- [ACTION_6]\n\n"
            "Month 7-9: [PHASE_3_NAME]\n"
            "- [ACTION_7]\n- [ACTION_8]\n- [ACTION_9]\n\n"
            "The secret? [KEY_INSIGHT].\n\n"
            "[PRINCIPLE]. Then expand."
        ),
        cta_pattern="Who else [DID_SIMILAR]? I'd love to hear your story.",
        example_post="",
        fill_instructions=(
            "HOOK: Before/after transformation with timeline.\n"
            "BODY: Step-by-step phased breakdown with specific actions and metrics.\n"
            "CTA: Invite others to share their journey.\n"
            "FORMAT: Use Month X-Y structure. Be very specific with numbers. Target ~250 words."
        ),
    ),
    PostTemplate(
        name="The Myth Buster",
        hook_pattern="Stop [COMMON_ACTION] for your [BUSINESS_TYPE].\n\nSeriously.",
        body_pattern=(
            "I've [CREDIBILITY_STATEMENT].\n\n"
            "The ones [BAD_OUTCOME]?\n"
            "They're all [BAD_PATTERN].\n\n"
            "The ones [GOOD_OUTCOME]?\n\n"
            "They all have this in common:\n\n"
            "✅ [POINT_1]\n✅ [POINT_2]\n✅ [POINT_3]\n"
            "✅ [POINT_4]\n✅ [POINT_5]\n\n"
            "[TOOL/APPROACH] isn't sexy. But it's [IMPRESSIVE_STAT].\n\n"
            "Why? Because [KEY_REASON].\n\n"
            "Your job isn't to [WRONG_GOAL].\n"
            "Your job is to [RIGHT_GOAL].\n\n"
            "[TOOL/APPROACH] does that better than any platform."
        ),
        cta_pattern="Follow me for more [NICHE] breakdowns.\n\n#[TAG1] #[TAG2] #[TAG3]",
        example_post="",
        fill_instructions=(
            "HOOK: Provocative command to stop doing something common.\n"
            "BODY: Credibility statement, then contrast bad vs good patterns with checkmark list.\n"
            "CTA: Follow CTA with hashtags.\n"
            "FORMAT: Use ✅ bullets. Target ~200 words."
        ),
    ),
    PostTemplate(
        name="The Data Drop",
        hook_pattern="[IMPRESSIVE_STAT] of [SUBJECT] [SURPRISING_FACT].",
        body_pattern=(
            "I analyzed [SAMPLE_SIZE] and found:\n\n"
            "📊 [DATA_POINT_1]\n📊 [DATA_POINT_2]\n📊 [DATA_POINT_3]\n\n"
            "The biggest surprise?\n\n"
            "[UNEXPECTED_FINDING].\n\n"
            "Here's what the top [PERCENTAGE] do differently:\n\n"
            "1. [TACTIC_1]\n2. [TACTIC_2]\n3. [TACTIC_3]\n\n"
            "The data doesn't lie."
        ),
        cta_pattern="Which of these surprised you the most?",
        example_post="",
        fill_instructions=(
            "HOOK: Lead with a surprising statistic.\n"
            "BODY: Present data points, reveal unexpected finding, then actionable tactics.\n"
            "CTA: Ask which data point surprised them most.\n"
            "FORMAT: Use 📊 for data points, numbered list for tactics. Target ~150 words."
        ),
    ),
    PostTemplate(
        name="The Quick Tips",
        hook_pattern="[NUMBER] [SUBJECT] tips that [IMPRESSIVE_OUTCOME]:",
        body_pattern=(
            "1. [TIP_1]\n   [BRIEF_EXPLANATION]\n\n"
            "2. [TIP_2]\n   [BRIEF_EXPLANATION]\n\n"
            "3. [TIP_3]\n   [BRIEF_EXPLANATION]\n\n"
            "4. [TIP_4]\n   [BRIEF_EXPLANATION]\n\n"
            "5. [TIP_5]\n   [BRIEF_EXPLANATION]\n\n"
            "Bookmark this for later."
        ),
        cta_pattern="Which tip are you trying first? Drop a number below 👇",
        example_post="",
        fill_instructions=(
            "HOOK: Number + topic + compelling outcome.\n"
            "BODY: 5 numbered tips, each with one line of explanation.\n"
            "CTA: Ask which one they'll try first.\n"
            "FORMAT: Numbered list, one blank line between items. Target ~150 words."
        ),
    ),
    # ── Kleo-inspired frameworks (proven viral structures) ──────────
    PostTemplate(
        name="The AIDA Formula",
        hook_pattern="It's impossible to [ACHIEVE_COMMON_GOAL]...\n\nAt least, that's what everyone says.",
        body_pattern=(
            "But what if you could:\n\n"
            "→ [SPECIFIC_ACTION_1] to [OUTCOME_1]\n"
            "→ [SPECIFIC_ACTION_2] to [OUTCOME_2]\n"
            "→ [SPECIFIC_ACTION_3] to [OUTCOME_3]\n"
            "→ [SPECIFIC_ACTION_4] to [OUTCOME_4]\n\n"
            "In [TIMEFRAME], you'll have:\n\n"
            "1. [DESIRABLE_OUTCOME_1]\n"
            "2. [DESIRABLE_OUTCOME_2]\n"
            "3. [DESIRABLE_OUTCOME_3]\n\n"
            "Stop saying \"[OLD_MINDSET].\"\n\n"
            "Start saying \"[NEW_MINDSET].\""
        ),
        cta_pattern="Which of these would change your business the most?",
        example_post="",
        fill_instructions=(
            "HOOK: Open by challenging a commonly held 'impossible' belief in e-commerce.\n"
            "BODY: Follow AIDA — Attention (the impossible claim), Interest (4 specific actions), "
            "Desire (3 outcomes they'll achieve), Action (mindset shift).\n"
            "CTA: Ask which outcome resonates most.\n"
            "FORMAT: Use arrow bullets for actions, numbered list for outcomes. 150-250 words."
        ),
    ),
    PostTemplate(
        name="The Authority Reference",
        hook_pattern="[PERSON_OR_BRAND] [REMARKABLE_ACHIEVEMENT] with [TOPIC].\n\nHere's what most people miss about how they did it:",
        body_pattern=(
            "[CONTEXT_SENTENCE]\n\n"
            "The [NUMBER] things that made the difference:\n\n"
            "1. [TIP_1]\n   [BRIEF_EXPLANATION]\n\n"
            "2. [TIP_2]\n   [BRIEF_EXPLANATION]\n\n"
            "3. [TIP_3]\n   [BRIEF_EXPLANATION]\n\n"
            "4. [TIP_4]\n   [BRIEF_EXPLANATION]\n\n"
            "The pattern? [KEY_INSIGHT]."
        ),
        cta_pattern="What would you add to this list?",
        example_post="",
        fill_instructions=(
            "HOOK: Reference a specific brand, client, or industry figure and their remarkable result.\n"
            "BODY: Break down their success into 4 numbered insights from your agency perspective.\n"
            "CTA: Invite audience to add their own observations.\n"
            "FORMAT: Numbered tips with one-line explanations. 150-200 words. Use specific numbers."
        ),
    ),
    PostTemplate(
        name="The Slippery Slide",
        hook_pattern="One word.\n\nThat's all it took.",
        body_pattern=(
            "Let me explain.\n\n"
            "[SHORT_SENTENCE_1]\n\n"
            "[SHORT_SENTENCE_2]\n\n"
            "[CONCEPT_1] = [OUTCOME_1]\n"
            "[CONCEPT_2] = [OUTCOME_2]\n\n"
            "But here's what nobody tells you:\n\n"
            "It's not the [SURFACE_DESIRE] we want.\n\n"
            "It's the [DEEPER_DESIRE].\n\n"
            "I've spent [TIMEFRAME] working with [RELEVANT_PEOPLE].\n\n"
            "[KEY_INSIGHT_FROM_EXPERIENCE].\n\n"
            "The ones who win? They [WINNING_BEHAVIOR]."
        ),
        cta_pattern="What's the one word that changed your approach to [TOPIC]?",
        example_post="",
        fill_instructions=(
            "HOOK: Ultra-short sentences (under 6 words each) that create reading momentum.\n"
            "BODY: Build from short punchy lines to a deeper insight. Each sentence's SOLE PURPOSE "
            "is to get them to read the next one. Reveal a counterintuitive truth.\n"
            "CTA: Ask a simple one-word or one-line question.\n"
            "FORMAT: Very short opening sentences. Every line earns the next. 150-200 words."
        ),
    ),
    PostTemplate(
        name="The Transformation Arc",
        hook_pattern="[TIME_PERIOD] ago, [STARTING_SITUATION].\n\n[BRIEF_DISADVANTAGE].\n\nToday? [IMPRESSIVE_CURRENT_STATE].",
        body_pattern=(
            "Here's what happened in between:\n\n"
            "I didn't have [ADVANTAGE_1].\n"
            "I didn't have [ADVANTAGE_2].\n"
            "I didn't have [ADVANTAGE_3].\n\n"
            "But I had [KEY_ASSET].\n\n"
            "So I [ACTION_1].\n"
            "Then I [ACTION_2].\n"
            "Then I [ACTION_3].\n\n"
            "Result: [MEASURABLE_OUTCOME].\n\n"
            "This isn't a brag.\n\n"
            "It's proof that [UNIVERSAL_TRUTH].\n\n"
            "You may not control where you start.\n"
            "But you control where you finish."
        ),
        cta_pattern="What's your transformation story? I'd love to hear it.",
        example_post="",
        fill_instructions=(
            "HOOK: Before/after contrast — humble beginning vs impressive present.\n"
            "BODY: List what you DIDN'T have (relatability), then what you DID (actions), "
            "then the result. End with a universal truth that inspires.\n"
            "CTA: Invite others to share their own transformation.\n"
            "FORMAT: Short declarative sentences. Use specific numbers. 200-250 words."
        ),
    ),
    PostTemplate(
        name="The Conflict Story",
        hook_pattern="Once upon a time.\n\nI [EXPERIENCED_CHALLENGING_SITUATION].",
        body_pattern=(
            "Here's what it looked like:\n\n"
            "- [PROBLEM_1_AND_IMPACT]\n"
            "- [PROBLEM_2_AND_IMPACT]\n"
            "- [PROBLEM_3_AND_IMPACT]\n\n"
            "Sound familiar? You've probably seen this too.\n\n"
            "But here's what I could never understand:\n\n"
            "Why does [SPECIFIC_ISSUE] always lead to [NEGATIVE_CONSEQUENCE]?\n\n"
            "So I dug in.\n\n"
            "Turns out the answer is simpler than you'd think:\n\n"
            "[KEY_REVELATION]\n\n"
            "Once I understood that, everything changed.\n\n"
            "[SPECIFIC_RESULT_WITH_NUMBERS]."
        ),
        cta_pattern="Have you ever experienced this? What did you do differently?",
        example_post="",
        fill_instructions=(
            "HOOK: 'Once upon a time' opening — instantly signals a story. State the challenge.\n"
            "BODY: 3 bullet points showing the problem's impact, then a rhetorical question, "
            "then the revelation and result. Build tension before the payoff.\n"
            "CTA: Ask if they've experienced the same thing.\n"
            "FORMAT: Story structure with tension and resolution. Bullet points for problems. 200-250 words."
        ),
    ),
    PostTemplate(
        name="The PAS Formula",
        hook_pattern="[IMPRESSIVE_RELATABLE_FACT].\n\n[SUPPORTING_FACT].\n\nThis explains why [CONNECTION_TO_AUDIENCE].",
        body_pattern=(
            "Because of this, [NEGATIVE_CONSEQUENCE_THEY_FACE].\n\n"
            "And it's costing them [SPECIFIC_COST].\n\n"
            "So how do you fix it?\n\n"
            "[NAME_THE_SOLUTION].\n\n"
            "Here are [NUMBER] actionable steps:\n\n"
            "1. [TIP_1]\n"
            "2. [TIP_2]\n"
            "3. [TIP_3]\n"
            "4. [TIP_4]\n\n"
            "Take [TIMEFRAME] to implement these.\n\n"
            "You'll [UNLOCK_SPECIFIC_BENEFIT]."
        ),
        cta_pattern="Which step are you starting with today?",
        example_post="",
        fill_instructions=(
            "HOOK: Lead with an impressive fact, then connect it to the audience's reality.\n"
            "BODY: Follow PAS — Problem (the fact/pain), Agitate (the cost/consequence), "
            "Solve (name solution + 4 actionable steps). Include specific numbers.\n"
            "CTA: Ask which step they'll implement first.\n"
            "FORMAT: Fact-based opening, numbered action steps. 150-250 words."
        ),
    ),
    PostTemplate(
        name="The Do This Not That",
        hook_pattern="I've [CREDIBILITY_STATEMENT].\n\nHere are [NUMBER] things I'd NEVER do again:",
        body_pattern=(
            "1. [INEFFECTIVE_APPROACH_1]\n"
            "   [WHY_IT_FAILS]\n\n"
            "2. [INEFFECTIVE_APPROACH_2]\n"
            "   [WHY_IT_FAILS]\n\n"
            "3. [INEFFECTIVE_APPROACH_3]\n"
            "   [WHY_IT_FAILS]\n\n"
            "Here's what I'd do instead:\n\n"
            "1. [EFFECTIVE_STRATEGY_1]\n"
            "   [WHY_IT_WORKS]\n\n"
            "2. [EFFECTIVE_STRATEGY_2]\n"
            "   [WHY_IT_WORKS]\n\n"
            "3. [EFFECTIVE_STRATEGY_3]\n"
            "   [WHY_IT_WORKS]\n\n"
            "Remember: [TAKEAWAY_SUMMARIZING_IMPORTANCE]."
        ),
        cta_pattern="What would you add to the 'never do' list?",
        example_post="",
        fill_instructions=(
            "HOOK: Establish credibility, then tease the mistakes.\n"
            "BODY: Dual-list structure — 3 things NOT to do (with why), then 3 things TO do instead "
            "(with why). The contrast makes both lists more memorable.\n"
            "CTA: Ask what they'd add to the list.\n"
            "FORMAT: Numbered dual-list. Each item gets a one-line explanation. 200-250 words."
        ),
    ),
    PostTemplate(
        name="The Vulnerable Truth",
        hook_pattern="[TIME_PERIOD] ago, my [VENTURE] failed.\n\nCompletely.",
        body_pattern=(
            "Despite not having [SUPPORT_TYPE], I was determined to make it work.\n\n"
            "I [STRUGGLE_METHOD_1] for [TIMEFRAME].\n"
            "I [STRUGGLE_METHOD_2].\n"
            "I [SACRIFICE_MADE].\n\n"
            "Then [SPECIFIC_HARDSHIP_HIT].\n\n"
            "[SEVERE_CONSEQUENCE].\n\n"
            "For [TIMEFRAME], I dealt with [SPECIFIC_REPERCUSSIONS].\n\n"
            "But [TIME_AGO]... [POSITIVE_TURN].\n\n"
            "Because what you see online isn't the whole story.\n\n"
            "So if you're experiencing [SPECIFIC_HARDSHIP]:\n\n"
            "It won't last forever.\n\n"
            "[WISE_PARTING_ADVICE]."
        ),
        cta_pattern="What's a struggle you went through that shaped who you are today?",
        example_post="",
        fill_instructions=(
            "HOOK: Blunt admission of failure. No sugarcoating.\n"
            "BODY: Chronological struggle-to-recovery arc. Use vivid, sensory language (not bland). "
            "Show vulnerability without victimhood. Include the 'what you see online isn't real' reality check. "
            "End with hope and wisdom.\n"
            "CTA: Invite them to share their own struggle.\n"
            "FORMAT: Short emotional sentences. Chronological narrative. 200-250 words."
        ),
    ),
]


_cached_templates: list[PostTemplate] | None = None
_cached_by_name: dict[str, PostTemplate] | None = None


def get_all_templates() -> list[PostTemplate]:
    """Return all available templates (saved + built-in). Cached after first call."""
    global _cached_templates, _cached_by_name
    if _cached_templates is not None:
        return _cached_templates

    saved = load_saved_templates()
    saved_names = {t.name for t in saved}
    combined = list(saved)
    for t in BUILTIN_TEMPLATES:
        if t.name not in saved_names:
            combined.append(t)

    _cached_templates = combined
    _cached_by_name = {t.name: t for t in combined}
    return _cached_templates


def get_template_by_name(name: str) -> PostTemplate | None:
    """Find a template by exact name. Uses cached lookup dict."""
    global _cached_by_name
    if _cached_by_name is None:
        get_all_templates()
    return _cached_by_name.get(name)
