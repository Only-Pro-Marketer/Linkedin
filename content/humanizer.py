"""Deterministic quality engine: audit a draft and apply safe automatic fixes.

No AI call happens here, so the editor can re-check text on every keystroke.
Rules live in content/quality_rules.py (ported from linkedin-skills, MIT).

audit(text, kind)    -> score 0-100, status, blockers, warnings, tips, stats
auto_fix(text, kind) -> (text, changes) — only edits that cannot change meaning
"""

import re

from content.quality_rules import (
    DENSITY, GENERIC_CLOSERS, HARD_LIMITS, HOLLOW_WORDS, LENGTHS, MAX_NEWLINES, POST, RULES, SINCERITY_OPENER,
    WARN_NEWLINES,
)

_COMPILED_RULES = [(rule, re.compile(rule.pattern)) for rule in RULES]
_COMPILED_DENSITY = {name: re.compile(p) for name, p in DENSITY.items()}

LIST_LINE = re.compile(r"^\s*(?:\d+[.)]\s|[-•→✅✓▸▹➤*]\s|(?:Week|Month|Day|Year|Step|Phase)\s\d)")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")
TRIAD_RES = [
    re.compile(r"\b(\w+), (\w+),? and (\w+)\b", re.I),
    re.compile(r"\b(\w+ \w+), (\w+ \w+),? and (\w+ \w+)\b", re.I),
]

SCORE_BLOCKER = 18
SCORE_WARNING = 6
READY_THRESHOLD = 76


def _lines(text: str) -> list[str]:
    return [l for l in text.split("\n")]


def _first_line(text: str) -> str:
    return next((l.strip() for l in text.split("\n") if l.strip()), "")


def _last_line(text: str) -> str:
    return next((l.strip() for l in reversed(text.split("\n")) if l.strip()), "")


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def em_dash_cap(words: int) -> int:
    return max(1, min(2, round(words / 100)))


def _issue(rule_id, severity, message, fix, match=""):
    return {"id": rule_id, "severity": severity, "message": message, "fix": fix, "match": match[:120]}


def paragraph_density(paragraph: str) -> list[dict]:
    hits = []
    for name, rx in _COMPILED_DENSITY.items():
        for m in rx.finditer(paragraph):
            hits.append({"type": name, "text": m.group(0).strip()})
    return hits


def _triads(text: str) -> list[tuple]:
    found, seen = [], set()
    for rx in TRIAD_RES:
        for m in rx.finditer(text):
            if m.start() in seen:
                continue
            seen.add(m.start())
            found.append((m.group(0), m.groups()))
    return found


def _is_hollow(items) -> bool:
    for item in items:
        if re.search(r"[0-9$%]", item) or any(w[:1].isupper() for w in item.split()[1:]):
            return False
        if item.lower().split()[-1] not in HOLLOW_WORDS:
            return False
    return True


def _fragments(text: str) -> int:
    count = 0
    for line in text.split("\n"):
        if not line.strip() or LIST_LINE.match(line):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line.strip()):
            if 0 < len(sentence.split()) < 4 and not sentence.endswith("?"):
                count += 1
    return count


def audit(text: str, kind: str = POST) -> dict:
    """Check a draft. Returns score, status, blockers, warnings, tips, stats, paragraphs."""
    text = (text or "").replace("\r\n", "\n").strip()
    blockers: list[dict] = []
    warnings: list[dict] = []
    tips: list[str] = []

    words = len(text.split())
    chars = len(text)
    newlines = text.count("\n")
    first, last = _first_line(text), _last_line(text)
    stats = {
        "chars": chars, "words": words, "newlines": newlines, "hook_chars": len(first),
        "em_dashes": text.count("—"), "em_dash_cap": em_dash_cap(words),
        "hashtags": len(re.findall(r"(?<!\w)#\w+", text)), "emoji": len(EMOJI_RE.findall(text)),
        "fragments": _fragments(text), "triads": 0, "max_paragraph_density": 0,
    }

    if not text:
        blockers.append(_issue("empty", "blocker", "The draft is empty", "Write something first."))
        return _finish(blockers, warnings, tips, stats, [])

    # Hard limits
    if chars > HARD_LIMITS[kind]:
        blockers.append(_issue("too_long", "blocker", f"Over LinkedIn's {HARD_LIMITS[kind]:,}-character limit ({chars:,})",
                               "Cut it down."))
    if kind == POST and newlines > MAX_NEWLINES:
        blockers.append(_issue("too_many_lines", "blocker",
                               f"{newlines} line breaks — LinkedIn silently cuts posts after about {MAX_NEWLINES}",
                               "Merge short paragraphs or remove blank lines."))
    elif kind == POST and newlines > WARN_NEWLINES:
        warnings.append(_issue("many_lines", "warning", f"{newlines} line breaks — close to LinkedIn's {MAX_NEWLINES} limit",
                               "Merge a few short paragraphs."))

    # Pattern rules
    for rule, rx in _COMPILED_RULES:
        if kind not in rule.kinds:
            continue
        target = first if rule.scope == "opener" else last if rule.scope == "closer" else text
        m = rx.search(target)
        if m:
            bucket = blockers if rule.severity == "blocker" else warnings
            bucket.append(_issue(rule.id, rule.severity, rule.message, rule.fix, m.group(0).strip() or target))

    # Em dash density
    excess = stats["em_dashes"] - stats["em_dash_cap"]
    if excess > 0:
        blockers.append(_issue("em_dashes", "blocker",
                               f"{stats['em_dashes']} em dashes (about {stats['em_dash_cap']} is the natural maximum here)",
                               "Use Auto-fix: extra dashes become commas.", "—"))

    # Paragraph density
    para_report = []
    for i, p in enumerate(paragraphs(text)):
        hits = paragraph_density(p)
        para_report.append({"index": i, "density": len(hits), "hits": hits})
        stats["max_paragraph_density"] = max(stats["max_paragraph_density"], len(hits))
        if len(hits) >= 3:
            blockers.append(_issue("dense_paragraph", "blocker",
                                   f"Paragraph {i + 1} has {len(hits)} AI-sounding markers",
                                   "Rewrite that paragraph in plain words (Fix with AI can do it).",
                                   ", ".join(h["text"] for h in hits[:4])))
        elif len(hits) == 2:
            warnings.append(_issue("two_markers", "warning",
                                   f"Paragraph {i + 1} has 2 AI-sounding words", "Replace one of them.",
                                   ", ".join(h["text"] for h in hits)))

    # Rule of three
    triads = _triads(text)
    stats["triads"] = len(triads)
    hollow = [t for t in triads if _is_hollow(t[1])]
    if hollow:
        warnings.append(_issue("hollow_triad", "warning", "Hollow list of three (interchangeable words)",
                               "Use two items, or make each one concrete.", hollow[0][0]))
    elif len(triads) >= 3:
        warnings.append(_issue("many_triads", "warning", f"{len(triads)} lists of three in one post",
                               "Keep one; rewrite the others.", triads[1][0]))

    # Fragments
    if kind == POST and stats["fragments"] > 2:
        warnings.append(_issue("fragments", "warning", f"{stats['fragments']} very short fragment sentences",
                               "Keep at most two; join the rest to a neighbouring sentence."))

    # Length
    lo, sweet_lo, sweet_hi, hi = LENGTHS[kind]
    if chars < lo:
        warnings.append(_issue("short", "warning", f"Short for a LinkedIn {kind} ({chars} characters)",
                               f"Aim for {sweet_lo:,}–{sweet_hi:,} characters."))
    elif chars > hi and chars <= HARD_LIMITS[kind]:
        warnings.append(_issue("long", "warning", f"Long for a LinkedIn {kind} ({chars:,} characters)",
                               f"Aim for {sweet_lo:,}–{sweet_hi:,} characters."))
    elif not (sweet_lo <= chars <= sweet_hi):
        tips.append(f"Sweet spot is {sweet_lo:,}–{sweet_hi:,} characters (now {chars:,}).")

    if kind == POST:
        if len(first) > 210:
            warnings.append(_issue("long_hook", "warning", "First line runs past the “…see more” cut (210 characters)",
                                   "Shorten the hook so it lands before the fold.", first[:60]))
        elif len(first) > 140:
            tips.append("On mobile the fold is around 140 characters; tighten the hook if you can.")
        if not re.search(r"\d", first):
            tips.append("A specific number in the first line tends to lift reach.")
        lines = [l for l in text.split("\n")]
        if len(lines) >= 3 and lines[1].strip():
            warnings.append(_issue("no_hook_gap", "warning", "No blank line after the hook", "Add a blank line after line 1."))
        if not re.search(r"\d", text):
            warnings.append(_issue("no_numbers", "warning", "No specific numbers",
                                   "Add a real number with context (a date, amount, count or percentage)."))
        if stats["hashtags"] > 2:
            warnings.append(_issue("hashtags", "warning", f"{stats['hashtags']} hashtags", "Use 0–2, at the end."))
        if stats["emoji"] > 3:
            warnings.append(_issue("emoji", "warning", f"{stats['emoji']} emoji", "Keep it to 0–2."))
        if not last.endswith("?"):
            tips.append("A specific closing question invites comments.")
    else:
        if stats["hashtags"]:
            warnings.append(_issue("hashtags", "warning", "Hashtags in a comment", "Remove them."))

    return _finish(blockers, warnings, tips, stats, para_report)


def _finish(blockers, warnings, tips, stats, para_report) -> dict:
    score = max(0, 100 - SCORE_BLOCKER * len(blockers) - SCORE_WARNING * len(warnings))
    status = "fix" if blockers else ("ready" if score >= READY_THRESHOLD else "review")
    return {"score": score, "status": status, "blockers": blockers, "warnings": warnings, "tips": tips,
            "stats": stats, "paragraphs": para_report}


# ── Automatic fixes (safe, meaning-preserving, idempotent) ─────────────

_VERB_FORMS = {
    r"utiliz(?:e|es|ed|ing)": {"e": "use", "es": "uses", "ed": "used", "ing": "using"},
    r"leverag(?:es|ed|ing)": {"es": "uses", "ed": "used", "ing": "using"},
}


def _match_case(src: str, repl: str) -> str:
    return repl[:1].upper() + repl[1:] if src[:1].isupper() else repl


def _replace_verbs(text: str) -> tuple[str, int]:
    total = 0
    for stem_pattern, forms in _VERB_FORMS.items():
        def sub(m):
            word = m.group(0)
            suffix = re.match(r"(?i)(?:utiliz|leverag)(\w*)", word).group(1).lower()
            return _match_case(word, forms.get(suffix, word))
        text, n = re.subn(rf"\b{stem_pattern}\b", sub, text, flags=re.I)
        total += n
    return text, total


def _cap_em_dashes(text: str) -> tuple[str, int]:
    cap = em_dash_cap(len(text.split()))
    positions = [m for m in re.finditer(r"\s*—\s*", text)]
    if len(positions) <= cap:
        return text, 0
    out, last, replaced = [], 0, 0
    for i, m in enumerate(positions):
        out.append(text[last:m.start()])
        if i < cap:
            out.append(m.group(0))
        else:
            out.append(", ")
            replaced += 1
        last = m.end()
    out.append(text[last:])
    return "".join(out), replaced


def _capitalize_line_starts(text: str) -> str:
    return "\n".join((l[:1].upper() + l[1:]) if l[:1].islower() else l for l in text.split("\n"))


LINE_PREFIX_DELETIONS = [
    (re.compile(r"(?im)^(?:the (?:result|outcome|answer|lesson|catch|kicker|truth|secret|difference|pattern)\?|plot twist:|spoiler:)[ \t]+(?=\S)"),
     "Removed a reveal bridge (“The result?”)"),
    (re.compile(r"(?im)^here'?s the thing:[ \t]+(?=\S)"), "Removed “Here’s the thing:”"),
    (re.compile(SINCERITY_OPENER[4:] if SINCERITY_OPENER.startswith("(?i)") else SINCERITY_OPENER, re.I | re.M),
     None),  # placeholder, replaced below
]

PHRASE_DELETIONS = [
    (re.compile(r"(?i)\bin today'?s fast-paced world,?\s*"), "Removed “In today’s fast-paced world”"),
    (re.compile(r"(?i)\bat the end of the day,\s*"), "Removed “At the end of the day”"),
    (re.compile(r"(?i)\bthe (?:harsh|hard|uncomfortable) (?:truth|reality) is:?\s*"), "Removed “The hard truth is”"),
]

SINCERITY_PREFIX = re.compile(
    r"(?im)^[ \t]*(?:let me be (?:honest|real|direct|clear)|i'?ll be (?:honest|real|direct)|to be (?:direct|honest|transparent)|real talk|full transparency|not gonna lie)[:,.!—-]*[ \t]+(?=\S)"
)


def auto_fix(text: str, kind: str = POST) -> tuple[str, list[str]]:
    """Apply only fixes that cannot change the meaning. Safe to run repeatedly."""
    original = (text or "").replace("\r\n", "\n")
    t, changes = original, []

    new = t.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    if new != t:
        changes.append("Straightened curly quotes")
        t = new

    new = re.sub(r"[ \t]*--[ \t]*", ", ", t)
    new = re.sub(r"[ \t]+–[ \t]+", ", ", new)
    if new != t:
        changes.append("Replaced double/en dashes with commas")
        t = new

    t, n = _cap_em_dashes(t)
    if n:
        changes.append(f"Turned {n} extra em dash{'es' if n > 1 else ''} into commas")

    for rx, label in LINE_PREFIX_DELETIONS[:2]:
        new = rx.sub("", t)
        if new != t:
            changes.append(label)
            t = new

    new = SINCERITY_PREFIX.sub("", t)
    if new != t:
        changes.append("Removed a sincerity announcement")
        t = new

    for rx, label in PHRASE_DELETIONS:
        new = rx.sub("", t)
        if new != t:
            changes.append(label)
            t = new

    t, n = _replace_verbs(t)
    if n:
        changes.append("Replaced “utilize/leverage” with “use”")

    if kind == POST:
        from content.post_formatter import strip_hashtags
        lines = t.rstrip().split("\n")
        tail_tags = lines and all(w.startswith("#") for w in lines[-1].split()) and lines[-1].strip()
        if tail_tags and len(re.findall(r"(?<!\w)#\w+", t)) > 2:
            t = strip_hashtags(t)
            changes.append("Removed trailing hashtags")

    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r",\s*,", ",", t)
    t = _capitalize_line_starts(t).strip()
    return t, changes


def generic_closer(text: str) -> bool:
    return bool(re.search(GENERIC_CLOSERS, _last_line(text)))
