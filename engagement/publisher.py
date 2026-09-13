"""Engage publisher: approved comments go out one at a time through the LinkedIn API.

- Only approved drafts with a known post URN (and, for replies, the TOP-level
  parent comment) are published automatically. Everything else is "manual":
  the user copies the text and opens the post.
- The scheduler calls publish_due() every minute. It publishes at most one
  item, items are spaced 90–180 s apart, and ENGAGE_DAILY_CAP applies per day.
- 403: LinkedIn refused this app → every pending item switches to manual.
- 429: pause until Retry-After. 401: the user must reconnect.
- Timeout / 5xx: "unknown". It may have posted, so it is never retried automatically.
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

import app_settings
from auth.token_manager import TokenManager
from config import settings
from database.models import CompetitorPost, EngagementDraft
from linkedin.api_client import LinkedInAPIClient
from linkedin.url_parser import is_linkedin_url
from utils.timeutil import local_day_bounds_utc

logger = logging.getLogger(__name__)

MODE_KEY = "ENGAGE_API_MODE"  # "auto" or "manual" (after LinkedIn refused with 403)
MODE_REASON_KEY = "ENGAGE_API_MODE_REASON"
PAUSE_KEY = "ENGAGE_PAUSED_UNTIL"
SPACING_SECONDS = (90, 180)
FIRST_DELAY_SECONDS = (5, 30)
REACT_GAP_SECONDS = (8, 15)
MAX_COMMENT_CHARS = 1250
DEFAULT_PAUSE = timedelta(minutes=15)
STALE_AFTER = timedelta(minutes=10)
NEEDS_YOU = ("manual", "failed", "unknown")

RECONNECT = "LinkedIn needs to be reconnected (the login expired). Reconnect it, then retry."
NOT_CONNECTED = "LinkedIn isn't connected, so post this one yourself: Copy, then Open post."
MANUAL_HINT = "LinkedIn didn't allow this app to comment. Post it yourself: Copy, then Open post."
UNKNOWN_HINT = "LinkedIn didn't confirm this one. Open the post and check before retrying, or it may post twice."


# ── State ───────────────────────────────────────────────────

def api_mode(db: Session) -> str:
    return app_settings.get_value(db, MODE_KEY, "auto") or "auto"


def paused_until(db: Session, now: datetime | None = None) -> datetime | None:
    raw = app_settings.get_value(db, PAUSE_KEY)
    try:
        until = datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None
    return until if until and until > (now or datetime.utcnow()) else None


def _credentials(db: Session) -> tuple[str | None, str | None]:
    tm = TokenManager(db)
    return tm.get_valid_access_token(), tm.get_person_urn()


def published_today(db: Session) -> int:
    start, end = local_day_bounds_utc()
    return (db.query(EngagementDraft)
            .filter(EngagementDraft.status == "published", EngagementDraft.published_at >= start,
                    EngagementDraft.published_at < end)
            .count())


def status(db: Session) -> dict:
    token, actor = _credentials(db)
    count = lambda *s: db.query(EngagementDraft).filter(EngagementDraft.status.in_(s)).count()  # noqa: E731
    return {
        "mode": api_mode(db),
        "reason": app_settings.get_value(db, MODE_REASON_KEY, "") or "",
        "paused_until": paused_until(db),
        "published_today": published_today(db),
        "cap": settings.ENGAGE_DAILY_CAP,
        "scheduler": settings.SCHEDULER_ENABLED,
        "connected": bool(token and actor),
        "pending": count("approved", "publishing"),
        "needs_you": count(*NEEDS_YOU),
    }


def reset_api_mode(db: Session) -> None:
    """Let the API be tried again (for example after reconnecting with more permissions)."""
    app_settings.set_value(db, MODE_KEY, "auto")
    app_settings.set_value(db, MODE_REASON_KEY, "")


def can_auto_publish(draft: EngagementDraft) -> bool:
    if not draft.post_urn:
        return False
    return draft.kind != "reply" or bool(draft.parent_comment_urn)


def open_url(draft: EngagementDraft) -> str | None:
    if draft.post_url and is_linkedin_url(draft.post_url):
        return draft.post_url
    if draft.post_urn:
        return f"https://www.linkedin.com/feed/update/{draft.post_urn}/"
    return None


# ── User actions ────────────────────────────────────────────

def _next_slot(db: Session, now: datetime) -> datetime:
    last_pending = (db.query(func.max(EngagementDraft.publish_after))
                    .filter(EngagementDraft.status == "approved").scalar())
    last_published = (db.query(func.max(EngagementDraft.published_at))
                      .filter(EngagementDraft.status == "published").scalar())
    base = now
    if last_pending and last_pending >= now - timedelta(seconds=SPACING_SECONDS[0]):
        base = max(base, last_pending + timedelta(seconds=random.randint(*SPACING_SECONDS)))
    if last_published and last_published > now - timedelta(seconds=SPACING_SECONDS[0]):
        base = max(base, last_published + timedelta(seconds=random.randint(*SPACING_SECONDS)))
    if base == now:
        base = now + timedelta(seconds=random.randint(*FIRST_DELAY_SECONDS))
    return base


def approve(db: Session, draft: EngagementDraft, text: str | None = None, reaction: str | None = None,
            now: datetime | None = None) -> EngagementDraft:
    """Approve a draft: it is scheduled for the API, or marked manual when it can't be auto-posted."""
    from content.humanizer import audit

    if draft.status in ("published", "publishing"):
        raise ValueError("This one is already posted")
    text = (text if text is not None else draft.text or "").strip()
    if not text:
        raise ValueError("Pick or write the text first")
    if len(text) > MAX_COMMENT_CHARS:
        raise ValueError(f"LinkedIn comments are limited to {MAX_COMMENT_CHARS:,} characters")
    draft.text = text
    if reaction is not None:
        draft.reaction = reaction or None
    draft.quality_score = audit(text, draft.kind or "comment")["score"]
    draft.error = None

    token, actor = _credentials(db)
    if api_mode(db) == "manual":
        draft.status, draft.publish_after, draft.error = "manual", None, MANUAL_HINT
    elif not (token and actor):
        draft.status, draft.publish_after, draft.error = "manual", None, NOT_CONNECTED
    elif not can_auto_publish(draft):
        draft.status, draft.publish_after = "manual", None
    else:
        draft.status, draft.publish_after = "approved", _next_slot(db, now or datetime.utcnow())
    db.commit()
    return draft


def mark_done(db: Session, draft: EngagementDraft) -> EngagementDraft:
    """The user posted it by hand (or confirmed an 'unknown' one went through)."""
    draft.status, draft.published_at, draft.error = "published", datetime.utcnow(), None
    _after_publish(db, draft)
    db.commit()
    return draft


def skip(db: Session, draft: EngagementDraft) -> EngagementDraft:
    if draft.status in ("published", "publishing"):
        raise ValueError("This one is already posted")
    draft.status, draft.publish_after = "skipped", None
    db.commit()
    return draft


def retry(db: Session, draft: EngagementDraft) -> EngagementDraft:
    if draft.status not in ("failed", "unknown", "manual"):
        raise ValueError("Only failed, unconfirmed or manual items can be retried")
    return approve(db, draft)


def queue_first_comment(db: Session, post) -> EngagementDraft | None:
    """After the user's own post goes out, schedule its first comment (where links belong)."""
    text = (post.first_comment or "").strip()
    if not text or not post.linkedin_post_id:
        return None
    draft = EngagementDraft(kind="comment", source="first_comment", post_urn=post.linkedin_post_id,
                            post_url=post.linkedin_post_url, queued_post_id=post.id,
                            target_text=(post.content or "")[:2000], text=text[:MAX_COMMENT_CHARS], status="draft")
    db.add(draft)
    db.flush()
    return approve(db, draft)


def recover_stale(db: Session) -> int:
    """Items stuck in 'publishing' after a crash may or may not have posted."""
    cutoff = datetime.utcnow() - STALE_AFTER
    stale = (db.query(EngagementDraft)
             .filter(EngagementDraft.status == "publishing", EngagementDraft.updated_at < cutoff).all())
    for d in stale:
        d.status, d.error = "unknown", UNKNOWN_HINT
    if stale:
        db.commit()
        logger.warning("Marked %d interrupted engagement items as unknown", len(stale))
    return len(stale)


# ── Publishing ──────────────────────────────────────────────

def _after_publish(db: Session, draft: EngagementDraft) -> None:
    if draft.competitor_post_id:
        cp = db.get(CompetitorPost, draft.competitor_post_id)
        if cp and not cp.commented_at:
            cp.commented_at = datetime.utcnow()


def _pause(db: Session, draft: EngagementDraft, result: dict, now: datetime) -> dict:
    try:
        wait = timedelta(seconds=max(30, int(result.get("retry_after") or 0))) if result.get("retry_after") else DEFAULT_PAUSE
    except ValueError:
        wait = DEFAULT_PAUSE
    until = now + wait
    app_settings.set_value(db, PAUSE_KEY, until.isoformat())
    draft.status, draft.error = "approved", "LinkedIn asked the app to slow down. It will try again later."
    draft.publish_after = until
    db.commit()
    return {"ok": False, "status": draft.status, "code": 429}


def _switch_to_manual(db: Session, reason: str) -> None:
    app_settings.set_value(db, MODE_KEY, "manual")
    app_settings.set_value(db, MODE_REASON_KEY, reason[:200])
    for d in db.query(EngagementDraft).filter(EngagementDraft.status == "approved").all():
        d.status, d.publish_after, d.error = "manual", None, MANUAL_HINT


async def publish_item(db: Session, draft: EngagementDraft, sleep=asyncio.sleep) -> dict:
    """React (if chosen), then comment. Records the outcome on the draft."""
    now = datetime.utcnow()
    token, actor = _credentials(db)
    if not (token and actor):
        draft.status, draft.error = "failed", RECONNECT
        db.commit()
        return {"ok": False, "status": draft.status, "code": 401}

    draft.status = "publishing"
    db.commit()
    client = LinkedInAPIClient(token)

    if draft.reaction and not draft.reacted_at:
        root = (draft.reply_to_urn or draft.parent_comment_urn) if draft.kind == "reply" else draft.post_urn
        r = await client.create_reaction(actor, root, draft.reaction)
        if r["success"] or r.get("status_code") == 409:  # 409: already reacted
            draft.reacted_at = datetime.utcnow()
            db.commit()
            await sleep(random.randint(*REACT_GAP_SECONDS))
        elif r.get("status_code") == 429:
            return _pause(db, draft, r, now)
        elif r.get("status_code") == 401:
            draft.status, draft.error = "failed", RECONNECT
            db.commit()
            return {"ok": False, "status": draft.status, "code": 401}
        else:
            logger.warning("Reaction failed (%s); commenting anyway", r.get("status_code"))

    parent = draft.parent_comment_urn if draft.kind == "reply" else None
    r = await client.create_comment(actor, draft.post_urn, draft.text, parent_comment=parent)
    code = r.get("status_code")
    if r["success"]:
        draft.status, draft.published_at, draft.error = "published", datetime.utcnow(), None
        draft.linkedin_comment_urn = r.get("comment_urn")
        _after_publish(db, draft)
    elif code == 403:
        _switch_to_manual(db, f"LinkedIn answered 403: {r.get('error', '')[:120]}")
        draft.status, draft.error = "manual", MANUAL_HINT
    elif code == 429:
        return _pause(db, draft, r, now)
    elif code == 401:
        draft.status, draft.error = "failed", RECONNECT
    elif r.get("outcome") == "not_sent":
        draft.status, draft.error = "approved", r.get("error")
        draft.publish_after = now + timedelta(minutes=5)
    elif r.get("outcome") == "unknown" or (code and code >= 500):
        draft.status, draft.error = "unknown", UNKNOWN_HINT
    else:
        draft.status = "failed"
        draft.error = f"LinkedIn rejected it ({code}): {(r.get('error') or '')[:200]}"
    db.commit()
    return {"ok": draft.status == "published", "status": draft.status, "code": code}


async def publish_due(db: Session, now: datetime | None = None, sleep=asyncio.sleep) -> dict | None:
    """Publish the next due item, if any. Called every minute by the scheduler."""
    now = now or datetime.utcnow()
    if api_mode(db) == "manual" or paused_until(db, now):
        return None
    if published_today(db) >= settings.ENGAGE_DAILY_CAP:
        return None
    draft = (db.query(EngagementDraft)
             .filter(EngagementDraft.status == "approved", EngagementDraft.publish_after <= now)
             .order_by(EngagementDraft.publish_after, EngagementDraft.id)
             .first())
    if not draft:
        return None
    return await publish_item(db, draft, sleep=sleep)
