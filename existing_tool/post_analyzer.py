"""Post structure analysis engine for LinkedIn posts."""

import re
from existing_tool.models import PostStructure, HookType, BodyFormat, CTAType


class PostAnalyzer:
    """Analyzes the structure of a LinkedIn post into hook, body, and CTA."""

    EMOJI_PATTERN = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F"
        "\U00002600-\U000026FF\U0000200D\U0000FE0F]+",
        flags=re.UNICODE,
    )

    def analyze(self, post_text: str) -> PostStructure:
        text = post_text.strip()
        lines = text.split("\n")
        non_empty = [l for l in lines if l.strip()]

        hook = self._extract_hook(lines)
        hook_type = self._classify_hook(hook)
        cta = self._extract_cta(non_empty)
        cta_type = self._classify_cta(cta)
        body = self._extract_body(text, hook, cta)
        body_format = self._classify_body(body)
        hashtags = re.findall(r"#(\w+)", text)

        return PostStructure(
            hook=hook,
            hook_type=hook_type,
            body=body,
            body_format=body_format,
            cta=cta,
            cta_type=cta_type,
            line_count=len(non_empty),
            word_count=len(text.split()),
            uses_line_breaks=self._has_line_breaks(lines),
            uses_emoji=bool(self.EMOJI_PATTERN.search(text)),
            uses_hashtags=len(hashtags) > 0,
            hashtags=hashtags,
            whitespace_ratio=self._whitespace_ratio(lines),
        )

    # ── Hook extraction ────────────────────────────────────────────

    def _extract_hook(self, lines: list) -> str:
        """Extract the hook — text before the first blank line, up to 3 lines."""
        hook_lines = []
        for line in lines:
            if not line.strip() and hook_lines:
                break
            if line.strip():
                hook_lines.append(line.strip())
            if len(hook_lines) >= 3:
                break
        return "\n".join(hook_lines)

    def _classify_hook(self, hook: str) -> HookType:
        first = hook.split("\n")[0].strip() if hook else ""
        fl = first.lower()

        # Personal failure
        if re.search(
            r"^i (lost|failed|was fired|went broke|almost quit|got rejected|wasted)",
            fl,
        ):
            return HookType.PERSONAL_FAILURE
        if re.search(r"^my (business|startup|store|company)\s+(failed|crashed|lost)", fl):
            return HookType.PERSONAL_FAILURE

        # Contrarian
        if re.search(
            r"^(everyone says|most people think|the common advice|unpopular opinion|forget|stop|nobody talks)",
            fl,
        ):
            return HookType.CONTRARIAN

        # Listicle
        if re.search(r"^\d+\s+(things|ways|tips|lessons|mistakes|reasons|habits|rules|steps|signs)", fl):
            return HookType.LISTICLE

        # Statistic
        if re.search(r"^\d+[%]", fl) or re.search(r"^(only|over|nearly|almost|less than)\s+\d+", fl):
            return HookType.STATISTIC

        # Story opener
        if re.search(
            r"^(\d+\s+(years?|months?|weeks?|days?)\s+ago|i was|i spent|i built|i started|last year|in 20\d{2}|yesterday|two years ago|when i|my first|a client|a founder|someone told me|back in)",
            fl,
        ):
            return HookType.STORY_OPENER

        # Question
        if first.endswith("?") or re.search(
            r"^(who|what|why|how|when|where|do you|have you|did you|are you|is it|can you|would you)",
            fl,
        ):
            return HookType.QUESTION

        # Bold statement
        if re.search(r"^(stop|never|always|the truth|here\'?s the thing|this is|you don\'t)", fl):
            return HookType.BOLD_STATEMENT

        # Short punchy first line is often a bold statement
        if len(first.split()) <= 8 and first.endswith("."):
            return HookType.BOLD_STATEMENT

        return HookType.UNKNOWN

    # ── CTA extraction ─────────────────────────────────────────────

    def _extract_cta(self, non_empty: list) -> str:
        """Extract CTA — last 1-3 non-empty lines."""
        if len(non_empty) <= 3:
            return non_empty[-1].strip() if non_empty else ""
        return "\n".join(l.strip() for l in non_empty[-3:])

    def _classify_cta(self, cta: str) -> CTAType:
        cl = cta.lower()

        if re.search(r"(follow me|follow for|follow \w+ for)", cl):
            return CTAType.FOLLOW_FOR_MORE
        if re.search(r"(link in|check the comments|first comment|drop.+comment)", cl):
            return CTAType.LINK_IN_COMMENTS
        if re.search(r"(repost|share this|reshare)", cl):
            return CTAType.SHARE_IF_AGREE
        if re.search(r"(tag someone|tag a friend|tag a founder)", cl):
            return CTAType.TAG_SOMEONE
        if re.search(r"(dm me|book a call|grab your|get the|check out)", cl):
            return CTAType.SOFT_SELL
        if cta.strip().endswith("?"):
            return CTAType.ENGAGEMENT_QUESTION

        return CTAType.NONE

    # ── Body extraction & classification ───────────────────────────

    def _extract_body(self, full_text: str, hook: str, cta: str) -> str:
        body = full_text
        if hook:
            idx = body.find(hook)
            if idx >= 0:
                body = body[idx + len(hook) :]
        if cta:
            idx = body.rfind(cta)
            if idx >= 0:
                body = body[:idx]
        return body.strip()

    def _classify_body(self, body: str) -> BodyFormat:
        bl = body.lower()
        lines = [l.strip() for l in body.split("\n") if l.strip()]

        # Listicle: numbered or bulleted items
        numbered = sum(1 for l in lines if re.match(r"^(\d+[\.\):]|[-•→▸✅⭐])\s", l))
        if numbered >= 3:
            return BodyFormat.LISTICLE

        # Framework: contains structured headings or labeled sections
        if re.search(r"(step \d|phase \d|rule \d|pillar \d)", bl):
            return BodyFormat.FRAMEWORK

        # Lesson: contains "lesson", "learned", "takeaway"
        if re.search(r"(lesson|learned|takeaway|moral|key insight|here\'?s what)", bl):
            return BodyFormat.LESSON

        # Tips: contains "tip", "advice", "pro tip"
        if re.search(r"(tip[s]?:|advice:|pro tip|here\'?s how)", bl):
            return BodyFormat.TIPS

        # Story: narrative with first person or temporal markers
        story_signals = len(re.findall(r"\b(i |my |we |our |then |after |before |when |but then)\b", bl))
        if story_signals >= 3:
            return BodyFormat.STORY

        # Default to story if nothing else matches (most LinkedIn posts are stories)
        if len(lines) >= 3:
            return BodyFormat.STORY

        return BodyFormat.UNKNOWN

    # ── Formatting helpers ─────────────────────────────────────────

    def _has_line_breaks(self, lines: list) -> bool:
        """Check if the post uses deliberate line breaks (short lines with spacing)."""
        blank_count = sum(1 for l in lines if not l.strip())
        return blank_count >= 2

    def _whitespace_ratio(self, lines: list) -> float:
        if not lines:
            return 0.0
        blank = sum(1 for l in lines if not l.strip())
        return blank / len(lines)
