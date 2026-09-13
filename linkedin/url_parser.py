"""LinkedIn URL → URN parser.

Adapted from linkedin-skills/lib/url_parser.py by Serge Bulaev (MIT License,
see knowledge/LICENSE). Changes: only linkedin.com hosts are accepted, and the
`replyUrn` query parameter (the specific reply to react to) is parsed.

Handles:
1. Post URL ("Copy link to post"):   /posts/SLUG-activity-ID-XX, /posts/SLUG-share-ID-XX
2. Feed URL:                          /feed/update/urn:li:activity:ID (or ugcPost / share)
3. Comment URL ("Copy link to comment"):
   /feed/update/urn:li:activity:ID?commentUrn=urn:li:comment:(activity:ID,COMMENT_ID)
   optionally with &replyUrn=urn:li:comment:(activity:ID,REPLY_ID)

LinkedIn flattens reply threads to 2 levels: when replying to a reply, the
`parentComment` must be the TOP-level comment URN (see build_parent_comment_urn).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

ACTIVITY_SLUG_RE = re.compile(r"activity[-:](\d{15,25})")
SHARE_SLUG_RE = re.compile(r"share[-:](\d{15,25})")
UGCPOST_SLUG_RE = re.compile(r"ugcPost[-:](\d{15,25})")
COMMENT_URN_RE = re.compile(r"urn:li:comment:\((?:urn:li:)?(activity|ugcPost|share):(\d+)\s*,\s*(\d+)\)")


def is_linkedin_url(url: str) -> bool:
    host = (urlparse((url or "").strip()).hostname or "").lower()
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _comment_from(value: str):
    m = COMMENT_URN_RE.search(unquote(value or ""))
    if not m:
        return None
    kind, post_id, comment_id = m.groups()
    return f"urn:li:{kind}:{post_id}", comment_id


def parse_linkedin_url(url: str) -> dict:
    """Parse a LinkedIn post or comment URL into URNs.

    Returns {post_urn, post_activity_id, comment_id, comment_urn, reply_id,
    reply_urn, url_type} where url_type is "post", "comment" or "unknown".
    Non-LinkedIn URLs always return url_type "unknown".
    """
    out = {
        "post_activity_id": None, "post_urn": None,
        "comment_id": None, "comment_urn": None,
        "reply_id": None, "reply_urn": None,
        "url_type": "unknown",
    }
    raw = (url or "").strip()
    if not is_linkedin_url(raw):
        return out

    parsed = urlparse(raw)
    query = parse_qs(parsed.query)
    comment = _comment_from(query.get("commentUrn", [""])[0]) or _comment_from(raw)
    if comment:
        post_urn, comment_id = comment
        out.update(post_urn=post_urn, comment_id=comment_id,
                   comment_urn=f"urn:li:comment:({post_urn},{comment_id})", url_type="comment")
        if post_urn.startswith("urn:li:activity:"):
            out["post_activity_id"] = post_urn.rsplit(":", 1)[1]
        reply = _comment_from(query.get("replyUrn", [""])[0])
        if reply:
            out["reply_id"] = reply[1]
            out["reply_urn"] = f"urn:li:comment:({post_urn},{reply[1]})"
        return out

    decoded = unquote(parsed.path)
    for pattern, kind in ((UGCPOST_SLUG_RE, "ugcPost"), (SHARE_SLUG_RE, "share"), (ACTIVITY_SLUG_RE, "activity")):
        m = pattern.search(decoded)
        if m:
            pid = m.group(1)
            out["post_urn"] = f"urn:li:{kind}:{pid}"
            if kind == "activity":
                out["post_activity_id"] = pid
            out["url_type"] = "post"
            return out
    return out


def build_parent_comment_urn(post_urn: str, top_level_comment_id: str) -> str:
    """parentComment URN for a reply — always the TOP-level comment's id."""
    return f"urn:li:comment:({post_urn},{top_level_comment_id})"
