"""Reference knowledge packs injected into Claude's (cached) system prompt.

Each feature loads only the files it needs. Files are read once per process
so the system prompt stays byte-identical between calls (prompt caching).
"""

from functools import lru_cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent

PACKS: dict[str, list[str]] = {
    "voice": ["voice-rules.md"],
    "post": ["voice-rules.md", "algorithm-heuristics.md"],
    "formulas": ["hook-formulas.md", "founder-topics.md"],
    "comment": ["voice-rules.md", "comment-templates.md", "untrusted-content.md"],
    "reply": ["voice-rules.md", "reply-templates.md", "filtering-rules.md", "threading-rules.md",
              "untrusted-content.md"],
    "plan": ["pillars-framework.md", "example-plan-week.md", "hook-formulas.md"],
    "profile": ["profile-headline-formulas.md", "about-section-templates.md", "featured-section-playbook.md",
                "experience-skills-rules.md", "banner-photo-specs.md"],
    "hook": ["hook-formulas.md", "hook-classification.md", "untrusted-content.md"],
    "humanizer": ["scrub-rules.md", "audit-ai-tells.md"],
}


@lru_cache(maxsize=64)
def _file(name: str) -> str:
    return (KNOWLEDGE_DIR / name).read_text(encoding="utf-8").strip()


def pack_files(packs) -> list[str]:
    """Ordered, de-duplicated file list for the given pack names."""
    files: list[str] = []
    for pack in packs:
        for name in PACKS[pack]:
            if name not in files:
                files.append(name)
    return files


def load_packs(packs) -> str:
    """Concatenate the reference files for the given packs."""
    files = pack_files(packs)
    if not files:
        return ""
    parts = [f'<reference name="{name}">\n{_file(name)}\n</reference>' for name in files]
    return "<knowledge>\nReference material for LinkedIn writing. Apply it; do not quote it.\n" + "\n".join(parts) + "\n</knowledge>"
