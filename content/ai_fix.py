"""“Fix with AI”: a targeted rewrite that fixes only the problems the audit found."""

import llm
from content.quality_rules import POST

FIX_RULES = """You are an editor, not a writer. Fix only the listed problems in the draft.
- Keep the author's meaning, claims, facts, names and numbers. Never add new facts, names, numbers or quotes.
- Keep the author's voice, line breaks and length (within about 10%).
- Change as little as possible; untouched sentences stay word-for-word.
- Do not introduce new problems: no reveal bridges ("The result?"), no "It's not X, it's Y", no staccato fragments, no sincerity announcements, no generic closing question.
- If a problem needs information you do not have (e.g. a real number), rewrite that line so it no longer needs it.
Output only the corrected text."""

KIND_LABEL = {"post": "LinkedIn post", "comment": "LinkedIn comment", "reply": "reply to a LinkedIn comment"}


def fix_with_ai(text: str, report: dict, kind: str = POST) -> str:
    """Return a corrected draft. Raises llm.LLMError on failure."""
    problems = []
    for issue in report.get("blockers", []) + report.get("warnings", []):
        line = f"- {issue['message']}"
        if issue.get("match"):
            line += f' — e.g. "{issue["match"]}"'
        if issue.get("fix"):
            line += f" → {issue['fix']}"
        problems.append(line)
    if not problems:
        return text

    user = f"""Fix this {KIND_LABEL.get(kind, kind)}.

PROBLEMS TO FIX:
{chr(10).join(problems)}

DRAFT:
---
{text}
---"""
    packs = ("post", "humanizer") if kind == POST else ("comment", "humanizer")
    return llm.complete("ai_fix", user, packs=packs, instructions=FIX_RULES, effort="medium").text
