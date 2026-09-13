"""Learn my voice: propose Brand Voice sections from 3–6 of the author's real posts."""

import re

from pydantic import BaseModel, Field

import llm
from content.brand import editor_sections

MIN_SAMPLES, MAX_SAMPLES = 3, 6
MIN_SAMPLE_CHARS = 150
SECTION_TITLES = {
    "voice_and_tone": "My LinkedIn Voice & Tone",
    "fingerprint": "Voice Fingerprint",
    "never_use": "Words & Phrases I Never Use",
    "signature_lines": "Signature Lines",
}


class VoiceProfile(BaseModel):
    voice_and_tone: str = Field(description="Markdown bullets: overall tone, perspective, how the author talks to readers")
    fingerprint: str = Field(description="Markdown bullets: sentence rhythm, openers, punctuation and formatting habits, recurring words")
    never_use: str = Field(description="Markdown bullets: words, phrases and devices the author clearly avoids")
    signature_lines: list[str] = Field(description="2-4 lines copied word for word from the samples that sound most like the author")


def split_samples(text: str) -> list[str]:
    """Posts pasted in one box, separated by a line of --- (or three blank lines)."""
    parts = re.split(r"^\s*-{3,}\s*$|\n\s*\n\s*\n\s*\n", (text or "").replace("\r\n", "\n"), flags=re.M)
    return [p.strip() for p in parts if p and p.strip()]


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def learn_voice(samples: list[str]) -> dict:
    """Proposed sections next to the current ones. Nothing is saved here."""
    samples = [s.strip() for s in samples if len(s.strip()) >= MIN_SAMPLE_CHARS][:MAX_SAMPLES]
    if len(samples) < MIN_SAMPLES:
        raise ValueError(f"Paste at least {MIN_SAMPLES} of your own posts ({MIN_SAMPLE_CHARS}+ characters each), "
                         "with a line of --- between them")
    joined = "\n\n".join(f"[Post {i + 1}]\n{s[:3000]}" for i, s in enumerate(samples))
    user = f"""These LinkedIn posts were written by the author. Describe how they write so future drafts sound like them.

{llm.untrusted(joined, 'author_posts')}

Rules:
- Describe what is actually in the samples. Don't prescribe generic best practice.
- Keep bullets short and concrete ("Opens with a date or a number in 4 of 5 posts"), not bare adjectives.
- signature_lines are copied word for word from the samples."""
    profile = llm.complete_json("learn_voice", user, VoiceProfile, packs=("voice",), brand=False, effort="medium")

    corpus = _norm("\n".join(samples))
    candidates = [l.strip().strip('"“”').strip() for l in profile.signature_lines if l.strip()]
    verified = [l for l in candidates if _norm(l) and _norm(l) in corpus]
    proposed = {
        SECTION_TITLES["voice_and_tone"]: profile.voice_and_tone.strip(),
        SECTION_TITLES["fingerprint"]: profile.fingerprint.strip(),
        SECTION_TITLES["never_use"]: profile.never_use.strip(),
        SECTION_TITLES["signature_lines"]: "\n".join(f'- "{l}"' for l in verified),
    }
    current = {s["title"]: s["body"] for s in editor_sections()["guided"]}
    return {
        "sections": [{"title": t, "current": current.get(t, ""), "proposed": p} for t, p in proposed.items() if p],
        "dropped_lines": len(candidates) - len(verified),
        "samples": len(samples),
    }
