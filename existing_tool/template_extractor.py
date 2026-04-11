"""Extract reusable templates from analyzed LinkedIn posts."""

import re
from existing_tool.models import LinkedInPost, PostStructure, PostTemplate, HookType, BodyFormat, CTAType


class TemplateExtractor:
    """Converts analyzed posts into fill-in-the-blank templates."""

    TEMPLATE_NAMES = {
        (HookType.QUESTION, BodyFormat.LISTICLE): "The Curious List",
        (HookType.QUESTION, BodyFormat.STORY): "The Curious Story",
        (HookType.QUESTION, BodyFormat.FRAMEWORK): "The Inquiry Framework",
        (HookType.BOLD_STATEMENT, BodyFormat.STORY): "The Authority Story",
        (HookType.BOLD_STATEMENT, BodyFormat.LISTICLE): "The Bold List",
        (HookType.BOLD_STATEMENT, BodyFormat.FRAMEWORK): "The Authority Framework",
        (HookType.STORY_OPENER, BodyFormat.STORY): "The Narrative Arc",
        (HookType.STORY_OPENER, BodyFormat.LESSON): "The Hard Lesson",
        (HookType.STORY_OPENER, BodyFormat.LISTICLE): "The Story List",
        (HookType.CONTRARIAN, BodyFormat.FRAMEWORK): "The Myth Buster",
        (HookType.CONTRARIAN, BodyFormat.LISTICLE): "The Contrarian List",
        (HookType.CONTRARIAN, BodyFormat.STORY): "The Against-the-Grain",
        (HookType.PERSONAL_FAILURE, BodyFormat.STORY): "The Comeback",
        (HookType.PERSONAL_FAILURE, BodyFormat.LESSON): "The Expensive Lesson",
        (HookType.PERSONAL_FAILURE, BodyFormat.LISTICLE): "The Failure Debrief",
        (HookType.STATISTIC, BodyFormat.LISTICLE): "The Data Drop",
        (HookType.STATISTIC, BodyFormat.STORY): "The Numbers Story",
        (HookType.LISTICLE, BodyFormat.LISTICLE): "The Power List",
        (HookType.LISTICLE, BodyFormat.TIPS): "The Quick Tips",
    }

    def extract(self, post: LinkedInPost, structure: PostStructure) -> PostTemplate:
        hook_pattern = self._generalize(structure.hook)
        body_pattern = self._generalize_body(structure.body, structure.body_format)
        cta_pattern = self._generalize(structure.cta)
        name = self._get_name(structure)
        instructions = self._build_instructions(structure)

        return PostTemplate(
            name=name,
            hook_pattern=hook_pattern,
            body_pattern=body_pattern,
            cta_pattern=cta_pattern,
            example_post=post.content,
            fill_instructions=instructions,
        )

    def _get_name(self, structure: PostStructure) -> str:
        key = (structure.hook_type, structure.body_format)
        if key in self.TEMPLATE_NAMES:
            return self.TEMPLATE_NAMES[key]
        return f"The {structure.hook_type.value.replace('_', ' ').title()}"

    def _generalize(self, text: str) -> str:
        """Replace specific content with [PLACEHOLDER] markers."""
        result = text

        # Dollar amounts
        result = re.sub(r"\$[\d,]+(?:\.\d+)?[KMB]?", "[DOLLAR_AMOUNT]", result)

        # Percentages
        result = re.sub(r"\b\d{1,3}(?:\.\d+)?%", "[PERCENTAGE]", result)

        # Large numbers
        result = re.sub(r"\b\d{1,3}(?:,\d{3})+\b", "[BIG_NUMBER]", result)

        # Years
        result = re.sub(r"\b20[12]\d\b", "[YEAR]", result)

        # Time durations
        result = re.sub(r"\b\d+\s+(years?|months?|weeks?|days?|hours?)\b", "[TIME_PERIOD]", result)

        # Simple numbers in context
        result = re.sub(r"\b\d+[xX]\b", "[MULTIPLIER]", result)

        return result

    def _generalize_body(self, body: str, body_format: BodyFormat) -> str:
        """Generalize body with format-aware processing."""
        result = self._generalize(body)

        if body_format == BodyFormat.LISTICLE:
            # Replace list item content but keep structure
            lines = result.split("\n")
            new_lines = []
            item_num = 0
            for line in lines:
                if re.match(r"^(\d+[\.\):]|[-•→▸✅⭐])\s", line.strip()):
                    item_num += 1
                    prefix = re.match(r"^(\d+[\.\):]|[-•→▸✅⭐])\s", line.strip()).group()
                    new_lines.append(f"{prefix}[POINT_{item_num}]")
                else:
                    new_lines.append(line)
            result = "\n".join(new_lines)

        return result

    def _build_instructions(self, structure: PostStructure) -> str:
        parts = []

        # Hook instructions
        hook_tips = {
            HookType.QUESTION: "Start with a provocative question that your audience can't ignore. Make it specific to your niche.",
            HookType.BOLD_STATEMENT: "Open with a short, punchy statement that challenges conventional wisdom or states a strong opinion.",
            HookType.STORY_OPENER: "Begin with a personal story moment — use 'I was...', 'Last year...', or a specific time marker.",
            HookType.STATISTIC: "Lead with a surprising number or statistic that creates curiosity.",
            HookType.CONTRARIAN: "Start by stating what everyone believes, then signal you disagree. Use 'Everyone says X. They're wrong.'",
            HookType.PERSONAL_FAILURE: "Open with a vulnerable admission of failure. Be specific about what you lost or what went wrong.",
            HookType.LISTICLE: "Start with 'N things/ways/tips...' — the number itself creates a promise to the reader.",
        }
        parts.append(f"HOOK: {hook_tips.get(structure.hook_type, 'Write a compelling opening line.')}")

        # Body instructions
        body_tips = {
            BodyFormat.STORY: "Tell a narrative with a clear arc: situation → conflict → resolution. Use short paragraphs.",
            BodyFormat.LISTICLE: f"Use {structure.line_count // 2}-point numbered or bulleted list. Each point should be 1-2 lines max.",
            BodyFormat.FRAMEWORK: "Present a structured framework with labeled steps/phases/pillars.",
            BodyFormat.LESSON: "Share the key takeaway or lesson learned. Connect it back to the hook.",
            BodyFormat.TIPS: "Share actionable, specific tips. Each tip should be immediately usable.",
        }
        parts.append(f"BODY: {body_tips.get(structure.body_format, 'Develop your main point.')}")

        # CTA instructions
        cta_tips = {
            CTAType.ENGAGEMENT_QUESTION: "End with a question that invites your audience to share their own experience.",
            CTAType.FOLLOW_FOR_MORE: "End with a follow CTA that promises ongoing value.",
            CTAType.LINK_IN_COMMENTS: "Tease a resource and direct to the comments for a link.",
            CTAType.SHARE_IF_AGREE: "Ask readers to repost if they found value.",
            CTAType.SOFT_SELL: "Include a subtle mention of your product/service with a soft CTA.",
        }
        parts.append(f"CTA: {cta_tips.get(structure.cta_type, 'End with a clear call to action.')}")

        # Formatting
        fmt = []
        if structure.uses_line_breaks:
            fmt.append("Use line breaks between short sentences for readability")
        if structure.uses_emoji:
            fmt.append("Include relevant emoji (sparingly)")
        if structure.uses_hashtags:
            fmt.append(f"Add {len(structure.hashtags)} relevant hashtags at the end")
        fmt.append(f"Target ~{structure.word_count} words")
        parts.append(f"FORMAT: {'. '.join(fmt)}.")

        return "\n".join(parts)
