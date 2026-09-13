"""Template library — built-in post templates plus the F1–F20 hook formulas.

Built-ins were rewritten to follow the 2026 writing rules: no question or
"Stop X" openers, no reveal bridges ("The secret?"), no staccato runs, no
"It's not X, it's Y", and specific closing questions. Every [PLACEHOLDER]
must be filled with a real detail; the quality check blocks leftovers.
"""

import json
from pathlib import Path

from content.templates.formulas import FORMULAS, formula_templates
from existing_tool.models import PostTemplate

TEMPLATES_DIR = Path(__file__).parent  # user-added *.json templates are also loaded from here

REAL = "Use only facts from the brand profile or the topic; never invent results, clients or amounts."


def _t(name, hook, body, cta, notes):
    return PostTemplate(name=name, hook_pattern=hook, body_pattern=body, cta_pattern=cta,
                        example_post="", fill_instructions=f"{notes} {REAL}")


BUILTIN_TEMPLATES = [
    _t("The Expensive Lesson",
       "I lost [DOLLAR_AMOUNT] on [SPECIFIC_THING] in [MONTH_OR_YEAR].",
       "What went wrong, in order:\n\n1. [MISTAKE_1]\n2. [MISTAKE_2]\n3. [MISTAKE_3]\n\n"
       "It took [TIME_PERIOD] to recover.\n\n[WHAT_YOU_DO_DIFFERENTLY_NOW, one plain sentence].",
       "What's the most expensive lesson your [BUSINESS_TYPE] taught you?",
       "HOOK: a real, dated loss with a specific amount. BODY: three specific mistakes, the recovery, the one change you made. ~180 words."),
    _t("The Contrarian Take",
       "Everyone says [COMMON_BELIEF].\n\nIn [NUMBER] [SITUATIONS] I've seen, it was the wrong call.",
       "The [SUBJECT] that did best did [CONTRARIAN_ACTION] instead.\n\nThree reasons it worked:\n\n"
       "→ [REASON_1]\n→ [REASON_2]\n→ [REASON_3]\n\n[PROOF_POINT, with a number].",
       "Where have you seen [COMMON_BELIEF] fail in your own work?",
       "HOOK: the common belief, then your evidence against it. BODY: what worked instead and why. The contrarian claim is the post's one contrast. ~170 words."),
    _t("The Origin Story",
       "I spent [TIME_PERIOD] building the \"perfect\" [PRODUCT].\n\nThen [TURNING_POINT, with a number].",
       "[EARLY_METRIC]\n\nSo I tried something different: [UNCONVENTIONAL_ACTION].\n\n[LATER_METRIC]\n\n"
       "The [THING] never changed. The [KEY_VARIABLE] did.",
       "Which [KEY_VARIABLE] drives most of your [OUTCOME]?",
       "HOOK: time invested, then the turning point. BODY: the metric before and after one change. ~190 words."),
    _t("The Framework Post",
       "[TIME_PERIOD] ago I was [BAD_STATE, with a number].\n\nToday I [GOOD_STATE, with a number].",
       "Exactly what I did, step by step:\n\nMonth 1–3: [PHASE_1]\n- [ACTION_1]\n- [ACTION_2]\n\n"
       "Month 4–6: [PHASE_2]\n- [ACTION_3]\n- [ACTION_4]\n\n[KEY_INSIGHT, one plain sentence].",
       "Which phase would be hardest for your team, and why?",
       "HOOK: before/after with numbers. BODY: phased actions, each specific. ~220 words."),
    _t("The Myth Buster",
       "[NUMBER] [BUSINESS_TYPE]s I've worked with tried [COMMON_ACTION]. [HOW_MANY] regretted it.",
       "The ones that [BAD_OUTCOME] all [BAD_PATTERN].\n\nThe ones that [GOOD_OUTCOME] had this in common:\n\n"
       "✅ [POINT_1]\n✅ [POINT_2]\n✅ [POINT_3]\n\n[TOOL_OR_APPROACH] is unglamorous, and it [IMPRESSIVE_STAT].",
       "What's one \"best practice\" you stopped following, and what happened?",
       "HOOK: a number-first observation about a common practice. BODY: the losing pattern vs the winning one. ~180 words."),
    _t("The Data Drop",
       "[IMPRESSIVE_STAT] of [SUBJECT] [SURPRISING_FACT].",
       "I looked at [SAMPLE_SIZE] and found:\n\n→ [DATA_POINT_1]\n→ [DATA_POINT_2]\n→ [DATA_POINT_3]\n\n"
       "The biggest surprise was [UNEXPECTED_FINDING].\n\nWhat the top [PERCENTAGE] do differently:\n\n1. [TACTIC_1]\n2. [TACTIC_2]",
       "Which of these numbers matches what you see in your own [WORK_AREA]?",
       "HOOK: a surprising statistic with its source. BODY: data points, the surprise, two tactics. ~170 words."),
    _t("The Quick Tips",
       "[NUMBER] [SUBJECT] tips that [OUTCOME, with a number]:",
       "1. [TIP_1]: [ONE_LINE_WHY]\n2. [TIP_2]: [ONE_LINE_WHY]\n3. [TIP_3]: [ONE_LINE_WHY]\n"
       "4. [TIP_4]: [ONE_LINE_WHY]\n5. [TIP_5]: [ONE_LINE_WHY]",
       "Which one will you try first, and on what?",
       "HOOK: number + topic + a concrete outcome. BODY: five tips, one line of why each. ~160 words."),
    _t("The AIDA Formula",
       "Everyone says you can't [ACHIEVE_COMMON_GOAL] without [COMMON_REQUIREMENT].",
       "[PROOF, with a number, that it can be done]\n\nWhat it took:\n\n→ [ACTION_1] to [OUTCOME_1]\n"
       "→ [ACTION_2] to [OUTCOME_2]\n→ [ACTION_3] to [OUTCOME_3]\n\nIn [TIMEFRAME], that meant [RESULT].\n\n"
       "[MINDSET_SHIFT, one plain sentence].",
       "Which of these would change your [AREA] the most?",
       "AIDA: attention (the 'impossible' belief), interest (proof), desire (actions and outcomes), action (the shift). ~200 words."),
    _t("The Authority Reference",
       "[PERSON_OR_BRAND] [REMARKABLE_ACHIEVEMENT, with a number] with [TOPIC].",
       "[CONTEXT_SENTENCE]\n\nHow they did it comes down to [NUMBER] things:\n\n1. [INSIGHT_1]\n2. [INSIGHT_2]\n3. [INSIGHT_3]\n\n"
       "[THE_PATTERN, one plain sentence].",
       "What would you add from your own experience?",
       "HOOK: a real, public result by a named person or brand. BODY: the insights behind it, from your perspective. ~180 words."),
    _t("The Slippery Slide",
       "[ONE_SPECIFIC_WORD_OR_DETAIL] changed how I [ACTIVITY] in [MONTH_OR_YEAR].",
       "[SHORT_SETUP_SENTENCE]\n\n[WHAT_HAPPENED, with a number]\n\n"
       "[CONCEPT_1] led to [OUTCOME_1], and [CONCEPT_2] led to [OUTCOME_2].\n\n"
       "After [TIMEFRAME] working with [RELEVANT_PEOPLE], [KEY_INSIGHT].\n\nThe people who win [WINNING_BEHAVIOR].",
       "What's the one word or detail that changed your approach to [TOPIC]?",
       "Short, momentum-building sentences where each pulls the next — full sentences, never fragment stacks. ~170 words."),
    _t("The Transformation Arc",
       "[TIME_PERIOD] ago, [STARTING_SITUATION, with a number].\n\nToday, [CURRENT_STATE, with a number].",
       "What happened in between:\n\nI didn't have [ADVANTAGE_1] or [ADVANTAGE_2].\n\nI did have [KEY_ASSET].\n\n"
       "So I [ACTION_1], then [ACTION_2].\n\n[MEASURABLE_OUTCOME].\n\n"
       "You don't control where you start. You do control what you do next.",
       "What's one thing you did early that still pays off?",
       "HOOK: a real before/after. BODY: what you lacked, what you had, what you did. ~200 words."),
    _t("The Conflict Story",
       "In [MONTH_YEAR], I [CHALLENGING_SITUATION, with a number].",
       "What it looked like:\n\n- [PROBLEM_1_AND_IMPACT]\n- [PROBLEM_2_AND_IMPACT]\n\n"
       "I couldn't understand why [SPECIFIC_ISSUE] kept leading to [NEGATIVE_CONSEQUENCE], so I dug in.\n\n"
       "The answer was simpler than I expected: [KEY_REVELATION].\n\n[SPECIFIC_RESULT_WITH_NUMBERS].",
       "Have you run into [SPECIFIC_ISSUE]? What did you change?",
       "A dated story: the problem, the digging, the answer, the result. ~200 words."),
    _t("The PAS Formula",
       "[IMPRESSIVE_RELATABLE_FACT, with a number].",
       "[SUPPORTING_FACT]\n\nFor [AUDIENCE], that means [NEGATIVE_CONSEQUENCE], and it costs [SPECIFIC_COST].\n\n"
       "The fix is [NAME_THE_SOLUTION]:\n\n1. [STEP_1]\n2. [STEP_2]\n3. [STEP_3]\n\n"
       "Give it [TIMEFRAME] and you'll see [SPECIFIC_BENEFIT].",
       "Which step would you start with this week?",
       "PAS: problem (the fact), agitation (the cost), solution (named, with steps). ~190 words."),
    _t("The Do This Not That",
       "I've [CREDIBILITY_STATEMENT, with a number]. [NUMBER] things I'd never do again:",
       "1. [INEFFECTIVE_1]: [WHY_IT_FAILS]\n2. [INEFFECTIVE_2]: [WHY_IT_FAILS]\n3. [INEFFECTIVE_3]: [WHY_IT_FAILS]\n\n"
       "What I'd do instead:\n\n1. [EFFECTIVE_1]: [WHY_IT_WORKS]\n2. [EFFECTIVE_2]: [WHY_IT_WORKS]\n3. [EFFECTIVE_3]: [WHY_IT_WORKS]",
       "What would you add to the never-again list?",
       "Credibility first, then a don't list and a do list, one line of why each. ~210 words."),
    _t("The Vulnerable Truth",
       "In [MONTH_YEAR], my [VENTURE] failed completely.",
       "I had no [SUPPORT_TYPE], so I [STRUGGLE_METHOD] for [TIMEFRAME] and [SACRIFICE_MADE].\n\n"
       "Then [SPECIFIC_HARDSHIP], and [SEVERE_CONSEQUENCE].\n\nFor [TIMEFRAME], I dealt with [REPERCUSSIONS].\n\n"
       "[TIME_AGO], [POSITIVE_TURN].\n\nIf you're dealing with [SPECIFIC_HARDSHIP] right now, it won't last forever. [PARTING_ADVICE].",
       "What's a hard stretch that shaped how you work today?",
       "True stories only, stated plainly with dates; no announced candour. ~210 words."),
]


def load_saved_templates() -> list[PostTemplate]:
    """Load user-added templates from *.json files in this folder (archive/ is ignored)."""
    templates = []
    for file in TEMPLATES_DIR.glob("*.json"):
        try:
            data = json.loads(file.read_text())
            templates.append(PostTemplate(
                name=data["name"], hook_pattern=data["hook_pattern"], body_pattern=data["body_pattern"],
                cta_pattern=data["cta_pattern"], example_post=data.get("example_post", ""),
                fill_instructions=data.get("fill_instructions", ""),
            ))
        except (json.JSONDecodeError, KeyError):
            continue
    return templates


_rotation: list[PostTemplate] | None = None
_by_name: dict[str, PostTemplate] | None = None


def get_all_templates() -> list[PostTemplate]:
    """Templates used for automatic generation (built-ins + safe formulas + user JSON)."""
    global _rotation, _by_name
    if _rotation is None:
        saved = load_saved_templates()
        names = {t.name for t in saved}
        _rotation = saved + [t for t in BUILTIN_TEMPLATES + formula_templates(autogen_only=True) if t.name not in names]
        _by_name = {t.name: t for t in _rotation}
        for t in formula_templates():  # every formula is findable by name (Studio)
            _by_name.setdefault(t.name, t)
    return _rotation


def get_template_by_name(name: str) -> PostTemplate | None:
    if _by_name is None:
        get_all_templates()
    return _by_name.get(name)


__all__ = ["BUILTIN_TEMPLATES", "FORMULAS", "get_all_templates", "get_template_by_name"]
