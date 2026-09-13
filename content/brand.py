"""The user's brand voice (soul/soul.md), reloaded whenever the file changes.

Every prompt reads the brand through here, so edits made in the Brand Voice
page take effect on the next generation without restarting the app.
"""

import re
import threading
from pathlib import Path

from config import settings

SOUL_PATH = Path(__file__).resolve().parent.parent / "soul" / "soul.md"

# Template placeholders look like "[YOUR NAME]" or "[Pillar 1]".
PLACEHOLDER_RE = re.compile(r"\[(?:YOUR [^\]]+|Pillar \d[^\]]*|Service \d|Industry \d|Audience segment[^\]]*|"
                            r"Your [^\]]+|Describe [^\]]+|Write [^\]]+|Add [^\]]+|Set your [^\]]+|"
                            r"Never [^\]]+|How you [^\]]+|What makes [^\]]+|Key strengths|Type of content[^\]]*|"
                            r"What perspective[^\]]*|Describe your[^\]]*|Will be filled[^\]]*)\]")

# Sections the user must fill for good drafts, in the order the editor shows them.
KEY_SECTIONS = [
    "Who I Am",
    "What My Business Does",
    "Who I Talk To (Target Audience)",
    "My LinkedIn Voice & Tone",
    "Content Pillars (What I Post About)",
]

_lock = threading.Lock()
_cache: dict = {"mtime": None, "text": ""}


def soul_text() -> str:
    """Current contents of soul.md (cached until the file changes)."""
    try:
        mtime = SOUL_PATH.stat().st_mtime
    except FileNotFoundError:
        return ""
    with _lock:
        if _cache["mtime"] != mtime:
            _cache["text"] = SOUL_PATH.read_text(encoding="utf-8")
            _cache["mtime"] = mtime
        return _cache["text"]


def split_sections(text: str) -> dict[str, str]:
    """Map '## Heading' → body text (level-2 headings only)."""
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current, buf = line[3:].strip(), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def brand_status() -> dict:
    """How complete the brand profile is (drives the setup checklist)."""
    text = soul_text()
    if not text:
        return {"exists": False, "filled": False, "percent": 0, "placeholders": 0, "missing_sections": KEY_SECTIONS}
    sections = split_sections(text)
    missing = [
        name for name in KEY_SECTIONS
        if not sections.get(name) or PLACEHOLDER_RE.search(sections.get(name, ""))
    ]
    placeholders = len(PLACEHOLDER_RE.findall(text))
    percent = round(100 * (len(KEY_SECTIONS) - len(missing)) / len(KEY_SECTIONS))
    return {
        "exists": True,
        "filled": not missing,
        "percent": percent,
        "placeholders": placeholders,
        "missing_sections": missing,
    }


def get_niche() -> str:
    """One line describing the business, for prompts that need the niche."""
    sections = split_sections(soul_text())
    business = sections.get("What My Business Does", "")
    # The business description is the first non-empty line of that section.
    first = next((l.strip().strip("*").strip() for l in business.splitlines() if l.strip()), "")
    if first and not PLACEHOLDER_RE.search(first) and not first.endswith(":"):
        return first[:200]
    return settings.TARGET_NICHE


def get_pillars() -> list[str]:
    """Content pillars from the brand profile ("1. **Name** — description"), placeholders skipped."""
    body = split_sections(soul_text()).get("Content Pillars (What I Post About)", "")
    pillars = []
    for line in body.splitlines():
        s = line.strip()
        if not re.match(r"^(\d+[.)]|[-*])\s+", s) or PLACEHOLDER_RE.search(s):
            continue
        s = re.sub(r"^(\d+[.)]|[-*])\s+", "", s).replace("**", "").strip()
        if s:
            pillars.append(s[:160])
    return pillars


def author_identity() -> dict:
    """Name / role / company from the "Who I Am" section (blank if still placeholders)."""
    who = split_sections(soul_text()).get("Who I Am", "")

    def field(label: str) -> str:
        m = re.search(rf"\*\*{label}:\*\*\s*(.+)", who)
        value = m.group(1).strip() if m else ""
        return "" if not value or PLACEHOLDER_RE.search(value) or value.startswith("[") else value

    company = re.sub(r"\s*\(.*\)\s*$", "", field("Company"))
    return {"name": field("Name"), "role": field("Role"), "company": company}


# ── Guided editor (Brand Voice page) ───────────────────────────

GUIDED_SECTIONS = [
    ("Who I Am", "Name, role, company and location, then 2–3 sentences on what makes you credible.",
     "**Name:** Jane Doe\n**Role:** Founder\n**Company:** Acme Growth (acme.com)\n**Location:** Toronto\n\n"
     "I run a 9-person agency that helps DTC brands grow retention revenue. I've run email programs for 60+ brands since 2019."),
    ("What My Business Does", "Line 1 is a one-sentence description (the app uses it as your niche). Then services and industries.",
     "We are an e-commerce growth agency for DTC brands doing $1M–$20M a year.\n\n**Core services:**\n- Email & SMS\n- CRO\n- Paid social"),
    ("Who I Talk To (Target Audience)", "The people you want reading and commenting. Be specific.",
     "- DTC founders doing $1M–$20M\n- Heads of growth at Shopify brands"),
    ("Business Stage & Positioning", "How you're different, your focus, your strengths.",
     "- Retention-first: we fix email before we scale ads\n- Operator background, not agency-only"),
    ("My LinkedIn Voice & Tone", "How you sound. Keep what fits, delete what doesn't, and replace every [bracket].", ""),
    ("Voice Fingerprint", "How your writing actually sounds: rhythm, openers, punctuation habits, words you use a lot.",
     "- Mostly short sentences, one longer one per paragraph\n- I often open with a date or a number\n- I use \"..\" as a soft pause"),
    ("Words & Phrases I Never Use", "Banned words, clichés you hate, topics you avoid.",
     "- \"game-changer\", \"leverage\", \"synergy\"\n- No engagement bait, no \"Agree?\""),
    ("Signature Lines", "Paste 2–4 real lines or short posts that sound most like you. Drafts mirror these.",
     "- \"Most flows fail in the first email, not the fifth.\"\n- \"Retention is a product problem wearing a marketing costume.\""),
    ("Content Pillars (What I Post About)", "3–5 recurring themes as a numbered list: 1. **Name** — description.",
     "1. **Retention playbooks** — flows, offers, LTV\n2. **Agency life** — pricing, hiring, lessons"),
    ("Hashtags", "Your hashtag preference, e.g. \"No hashtags\" or \"1–2 niche tags at the end\".", "No hashtags."),
]
GUIDED_TITLES = [t for t, _, _ in GUIDED_SECTIONS]
META_SECTIONS = ("Post Templates I Use", "Past Posts & Performance", "How to Use This File")
MAX_SECTION_CHARS = 10000


def _clean_body(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    while text.endswith("---"):
        text = text[:-3].rstrip()
    return text


def parse_document(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split soul.md into (preamble, [(section title, body)]) preserving order."""
    preamble, sections, current, buf = "", [], None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is None:
                preamble = _clean_body(buf)
            else:
                sections.append((current, _clean_body(buf)))
            current, buf = line[3:].strip(), []
        else:
            buf.append(line)
    if current is None:
        return _clean_body(buf), []
    sections.append((current, _clean_body(buf)))
    return preamble, sections


def serialize_document(preamble: str, sections: list[tuple[str, str]]) -> str:
    parts = [f"## {title}\n\n{body}".rstrip() for title, body in sections]
    head = (preamble.rstrip() + "\n\n---\n\n") if preamble.strip() else ""
    return head + "\n\n---\n\n".join(parts) + "\n"


def editor_sections() -> dict:
    """Sections for the Brand Voice page: guided ones first, then the rest."""
    _, sections = parse_document(soul_text())
    existing = dict(sections)
    guided = []
    for title, hint, example in GUIDED_SECTIONS:
        body = existing.get(title, "")
        guided.append({"title": title, "hint": hint, "example": example, "body": body,
                       "done": bool(body.strip()) and not PLACEHOLDER_RE.search(body)})
    other = [{"title": t, "body": b} for t, b in sections if t not in GUIDED_TITLES]
    return {"guided": guided, "other": other}


def save_sections(updates: dict[str, str]) -> None:
    """Merge edited sections into soul.md (atomic write, previous copy kept as .bak)."""
    import os
    import shutil

    preamble, sections = parse_document(soul_text())
    if not preamble:
        preamble = "# Soul File — Your LinkedIn Brand Voice"
    titles = [t for t, _ in sections]
    merged = [(t, updates.get(t, b).strip()) for t, b in sections]
    insert_at = next((i for i, (t, _) in enumerate(merged) if t in META_SECTIONS), len(merged))
    for title in GUIDED_TITLES:  # new guided sections keep the guided order
        if title not in titles and updates.get(title, "").strip():
            merged.insert(insert_at, (title, updates[title].strip()))
            insert_at += 1

    content = serialize_document(preamble, merged)
    SOUL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SOUL_PATH.exists():
        shutil.copy2(SOUL_PATH, SOUL_PATH.with_name(SOUL_PATH.name + ".bak"))
    tmp = SOUL_PATH.with_name(SOUL_PATH.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, SOUL_PATH)
    with _lock:
        _cache["mtime"] = None


def brand_block() -> str:
    """The brand voice section injected into every system prompt."""
    text = soul_text().strip()
    status = brand_status()
    note = ""
    if not text:
        note = ("\nNo brand profile exists yet. Write in a neutral, first-person expert voice "
                "and do not invent personal facts.")
    elif not status["filled"]:
        note = ("\nThis brand profile is only partly filled in and still contains template "
                "placeholders in square brackets. Never output placeholder text. Where a detail is "
                "missing, keep the writing general and do not invent names, clients, numbers or results.")
    return f"<brand_voice>\n{text}\n</brand_voice>{note}"
