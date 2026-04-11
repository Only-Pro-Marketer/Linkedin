"""Format generated posts for LinkedIn publishing."""

import logging
import re

logger = logging.getLogger(__name__)

LINKEDIN_CHAR_LIMIT = 3000
# Max CONSECUTIVE blank lines (prevents triple/quad spacing).
# A single blank line between paragraphs is normal and not limited.
MAX_CONSECUTIVE_BLANKS = 2
# Cap total newlines (content lines + blank lines) — LinkedIn silently
# drops everything after a newline threshold regardless of character count.
# Post #91 was truncated at 38 newlines, post #118 at 38 newlines.
# Posts #134/#135 were truncated around 31-33 newlines.
# Safe zone is 25 or fewer newlines — tighten spacing before cutting content.
MAX_TOTAL_NEWLINES = 25



def format_for_linkedin(raw_content: str, topic: str = "") -> str:
    """Apply LinkedIn-specific formatting rules to generated content.

    Guards against silent truncation by LinkedIn's API by:
    1. Normalizing line endings (\r\n / \r → \n)
    2. Capping consecutive blank lines to MAX_CONSECUTIVE_BLANKS
    3. Capping total newlines to MAX_TOTAL_NEWLINES
    4. Truncating at sentence/paragraph boundaries (never mid-sentence)
    """
    text = raw_content.strip()
    original_len = len(text)

    # Normalize line endings — \r can cause LinkedIn API to truncate
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove markdown formatting (only at line starts, never mid-text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)  # Bold
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # Headers (line-start only)

    # Auto-add blank lines between standalone content lines, but only when
    # the total newline count won't exceed the limit.  List items and short
    # consecutive sentences stay grouped to avoid newline inflation.
    LIST_PATTERN = re.compile(
        r"^(\d+[\.\)]\s|[-•→✅✓▸▹➤]\s|"       # 1. / • / → / ✅
        r"(Week|Month|Day|Year|Step|Phase)\s\d)"  # Timeline: Month 1, Day 2, etc.
    )
    lines = text.split("\n")
    current_newlines = text.count("\n")

    # Only auto-space if we have headroom — skip if already near the limit
    if current_newlines < MAX_TOTAL_NEWLINES - 4:
        spaced: list[str] = []
        added = 0
        budget = MAX_TOTAL_NEWLINES - 4 - current_newlines  # leave margin
        for i, line in enumerate(lines):
            stripped = line.strip()
            spaced.append(stripped if stripped else "")
            if stripped and i + 1 < len(lines) and added < budget:
                next_stripped = lines[i + 1].strip()
                if next_stripped:
                    this_is_list = bool(LIST_PATTERN.match(stripped))
                    next_is_list = bool(LIST_PATTERN.match(next_stripped))
                    if not (this_is_list and next_is_list):
                        spaced.append("")
                        added += 1
        text = "\n".join(spaced).strip()
    else:
        # Already at/near limit — just normalize whitespace, don't add blanks
        text = "\n".join(line.strip() if line.strip() else "" for line in lines).strip()

    # Deduplicate consecutive blank lines
    lines = text.split("\n")
    formatted_lines = []
    prev_was_blank = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if not prev_was_blank:
                formatted_lines.append("")
            prev_was_blank = True
        else:
            prev_was_blank = False
            formatted_lines.append(stripped)

    text = "\n".join(formatted_lines).strip()

    # Collapse excessive CONSECUTIVE blank lines (e.g., triple/quad spacing)
    # Single blank lines between paragraphs are preserved — they're normal formatting.
    lines = text.split("\n")
    collapsed = []
    consecutive_blanks = 0
    for line in lines:
        if line.strip() == "":
            consecutive_blanks += 1
            if consecutive_blanks <= MAX_CONSECUTIVE_BLANKS:
                collapsed.append(line)
            # else: skip this extra blank line
        else:
            consecutive_blanks = 0
            collapsed.append(line)
    text = "\n".join(collapsed).strip()

    # Strip any hashtags that the AI may have generated
    text = strip_hashtags(text)

    # Cap total newlines — LinkedIn silently drops content past this threshold.
    # Strategy: FIRST collapse blank lines (tighten spacing) to preserve all
    # content text. Only cut content lines as a last resort.
    total_newlines = text.count("\n")
    if total_newlines > MAX_TOTAL_NEWLINES:
        lines = text.split("\n")
        original_newlines = total_newlines

        # ── Phase 1: Remove blank lines to reduce newline count ──
        # Keep removing blank lines (starting from middle of post, preserving
        # first and last blank lines for readability) until under the limit.
        # This tightens spacing without losing any actual content.
        compacted = []
        blank_positions = []
        for i, line in enumerate(lines):
            compacted.append(line)
            if line.strip() == "":
                blank_positions.append(i)

        # Remove blanks from inside the post (skip first and last few)
        # to preserve the hook spacing and CTA spacing
        if blank_positions:
            # Protect first 2 blank lines (hook area) and last 1 (CTA separator)
            removable = [
                pos for pos in blank_positions
                if pos > 4 and pos < len(lines) - 3
            ]
            # Remove blanks until we're under the limit
            removed = 0
            remove_set = set()
            for pos in removable:
                if total_newlines - removed <= MAX_TOTAL_NEWLINES:
                    break
                remove_set.add(pos)
                removed += 1

            if remove_set:
                lines = [line for i, line in enumerate(lines) if i not in remove_set]
                text = "\n".join(lines).strip()

        # ── Phase 2: If still over limit, cut content at paragraph boundary ──
        total_newlines = text.count("\n")
        if total_newlines > MAX_TOTAL_NEWLINES:
            lines = text.split("\n")

            # Preserve the last paragraph (CTA) — find where it starts
            last_para_start = len(lines)
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip() == "":
                    last_para_start = i + 1
                    break

            tail_lines = lines[last_para_start:]
            tail_newlines = len(tail_lines) - 1 if tail_lines else 0

            # Budget for the body = total allowed - tail - 1 (separator blank line)
            separator_cost = 1 if tail_lines else 0
            body_budget = MAX_TOTAL_NEWLINES - tail_newlines - separator_cost
            if body_budget < 10:
                body_budget = MAX_TOTAL_NEWLINES  # tail too big, just do simple trim
                tail_lines = []
                separator_cost = 0

            # Trim the body at a paragraph boundary
            cut_at = body_budget + 1
            for i in range(min(cut_at, len(lines)), max(cut_at - 5, 0), -1):
                if i < len(lines) and lines[i].strip() == "":
                    cut_at = i
                    break

            if tail_lines:
                trimmed = lines[:cut_at] + [""] + tail_lines
            else:
                trimmed = lines[:cut_at]
            text = "\n".join(trimmed).strip()

        # Final safety: if still over limit, do a hard trim
        if text.count("\n") > MAX_TOTAL_NEWLINES:
            final_lines = text.split("\n")
            text = "\n".join(final_lines[:MAX_TOTAL_NEWLINES + 1]).strip()

        logger.warning(
            "Post had %d newlines (limit %d), reduced to %d newlines. "
            "Phase 1 (blank-line collapse) removed %d blanks. CTA preserved.",
            original_newlines,
            MAX_TOTAL_NEWLINES,
            text.count("\n"),
            original_newlines - text.count("\n"),
        )

    # Trim to character limit — truncate at last paragraph or sentence boundary
    if len(text) > LINKEDIN_CHAR_LIMIT:
        truncated = text[:LINKEDIN_CHAR_LIMIT]
        # Try paragraph boundary first (last \n\n)
        last_para = truncated.rfind("\n\n")
        # Then sentence boundary (. ! ?)
        last_sentence = max(
            truncated.rfind(". "),
            truncated.rfind(".\n"),
            truncated.rfind("! "),
            truncated.rfind("!\n"),
            truncated.rfind("? "),
            truncated.rfind("?\n"),
        )
        # Pick the best cut point — must retain at least 50% of content
        half = LINKEDIN_CHAR_LIMIT // 2
        if last_para > half:
            text = truncated[:last_para].rstrip()
        elif last_sentence > half:
            text = truncated[: last_sentence + 1].rstrip()
        else:
            text = truncated.rstrip() + "..."
        logger.warning(
            "Post exceeded %d char limit, truncated from %d to %d chars.",
            LINKEDIN_CHAR_LIMIT,
            len(raw_content),
            len(text),
        )

    final_len = len(text)
    if final_len < original_len * 0.9:
        logger.warning(
            "Formatter removed significant content: %d chars → %d chars (%.0f%% loss). "
            "Input first_50=%r, Output first_50=%r, Output last_50=%r",
            original_len, final_len,
            (1 - final_len / original_len) * 100 if original_len else 0,
            raw_content[:50], text[:50], text[-50:],
        )

    return text


def strip_hashtags(content: str) -> str:
    """Remove any trailing hashtag lines from the post content.

    If the AI generated hashtags despite being told not to, strip them
    so the post goes out clean.
    """
    lines = content.rstrip().split("\n")

    # Walk backward and remove lines that are only hashtags / whitespace
    while lines:
        stripped = lines[-1].strip()
        if not stripped:
            lines.pop()
            continue
        # Check if line is entirely hashtags (e.g., "#ecommerce #DTC #shopify")
        if all(word.startswith("#") for word in stripped.split()):
            lines.pop()
            continue
        break

    return "\n".join(lines).rstrip()


def validate_length(content: str) -> dict:
    """Validate post length and return stats."""
    word_count = len(content.split())
    char_count = len(content)
    byte_count = len(content.encode("utf-8"))
    line_count = content.count("\n") + 1
    blank_lines = sum(1 for l in content.split("\n") if l.strip() == "")
    return {
        "valid": char_count <= LINKEDIN_CHAR_LIMIT,
        "word_count": word_count,
        "char_count": char_count,
        "byte_count": byte_count,
        "char_limit": LINKEDIN_CHAR_LIMIT,
        "line_count": line_count,
        "blank_lines": blank_lines,
    }


def validate_post_content(content: str) -> dict:
    """Comprehensive pre-posting validation.

    Returns a dict with:
      - valid: bool — True if safe to post
      - issues: list[str] — blockers that WILL cause truncation
      - warnings: list[str] — risks that MAY cause truncation
      - stats: dict — character, byte, newline, and word counts
      - content_hash: str — SHA-256 for post-publish integrity check
    """
    import hashlib

    char_count = len(content)
    byte_count = len(content.encode("utf-8"))
    total_newlines = content.count("\n")
    blank_lines = sum(1 for line in content.split("\n") if line.strip() == "")
    word_count = len(content.split())
    has_carriage_return = "\r" in content

    issues: list[str] = []
    warnings: list[str] = []

    # ── Blockers ──
    if char_count > LINKEDIN_CHAR_LIMIT:
        issues.append(f"Exceeds {LINKEDIN_CHAR_LIMIT} char limit ({char_count} chars)")

    if has_carriage_return:
        issues.append("Contains \\r (carriage return) — LinkedIn API may truncate at this character")

    if total_newlines > MAX_TOTAL_NEWLINES:
        issues.append(
            f"Too many newlines ({total_newlines}, limit {MAX_TOTAL_NEWLINES}) — "
            "LinkedIn will silently truncate"
        )

    if char_count == 0:
        issues.append("Post content is empty")

    # ── Warnings ──
    if byte_count > 4000:
        warnings.append(f"High UTF-8 byte count ({byte_count}) — may exceed LinkedIn byte limit")

    if total_newlines > 22:
        warnings.append(f"High newline count ({total_newlines}) — monitor for truncation")

    if blank_lines > 12:
        warnings.append(f"Many blank lines ({blank_lines}) — monitor for truncation")

    if word_count < 30:
        warnings.append(f"Very short post ({word_count} words)")

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "stats": {
            "char_count": char_count,
            "byte_count": byte_count,
            "word_count": word_count,
            "total_newlines": total_newlines,
            "blank_lines": blank_lines,
        },
        "content_hash": content_hash,
        "first_100": content[:100],
        "last_100": content[-100:] if len(content) > 100 else content,
    }
