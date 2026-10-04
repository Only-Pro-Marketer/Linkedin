"""Home ("Today"): what needs attention now, plus the setup checklist."""

import json
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

import llm
from auth.token_manager import TokenManager
from config import settings
from content.brand import author_identity, brand_status
from dashboard.common import render
from database.engine import get_db
from database.models import ContentCalendar, PostStatus, QueuedPost
from post_queue.post_queue import PostQueue
from utils.timeutil import local_now, posting_tz

router = APIRouter(tags=["home"])


def _local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(posting_tz())


def fmt_local(dt: datetime) -> str:
    """'Tue, Sep 15 · 8:30 AM' in the posting timezone (dt is local-aware)."""
    return f"{dt:%a, %b} {dt.day} · {dt.strftime('%I:%M %p').lstrip('0')}"


def first_line(text: str, limit: int = 140) -> str:
    line = next((l.strip() for l in (text or "").split("\n") if l.strip()), "")
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def next_slots(db: Session, count: int = 3) -> list[datetime]:
    """Next calendar posting slots (local-aware datetimes)."""
    from post_queue.slots import next_calendar_slots
    return next_calendar_slots(db, count)


FORMULA_CODE = re.compile(r"^F\d+\s+")


def plain_template(name: str) -> str:
    """'F10 Contrarian + Historical Receipts' -> 'Contrarian + Historical Receipts'.

    The formula code means nothing to the person reading the dashboard.
    """
    return FORMULA_CODE.sub("", name or "").strip() or "Draft"


def reach_word(score: int | None) -> str | None:
    """A predicted-reach number in words; the number alone reads as a grade."""
    if not score:
        return None
    return "strong" if score >= 70 else "fair" if score >= 45 else "weak"


def weekly_published(db: Session, weeks: int = 6) -> list[dict]:
    """Posts published per week, oldest first — the trend behind the headline numbers."""
    today = local_now().date()
    this_monday = today - timedelta(days=today.weekday())
    first_monday = this_monday - timedelta(weeks=weeks - 1)
    buckets = {first_monday + timedelta(weeks=i): 0 for i in range(weeks)}

    posted = (
        db.query(QueuedPost.posted_at)
        .filter(QueuedPost.status == PostStatus.POSTED, QueuedPost.posted_at.isnot(None))
        .all()
    )
    for (when,) in posted:
        day = _local(when).date()
        monday = day - timedelta(days=day.weekday())
        if monday in buckets:
            buckets[monday] += 1

    top = max(buckets.values()) or 1
    return [{"label": f"{m:%b} {m.day}", "count": n, "this_week": m == this_monday,
             "height": max(3, round(n / top * 64))}
            for m, n in sorted(buckets.items())]


def results_summary(db: Session) -> dict:
    """How many published posts have real LinkedIn numbers against them.

    Without these the app cannot learn what works, so the gap belongs on the
    dashboard rather than hidden in History.
    """
    from database.models import PostPerformance

    posted = db.query(QueuedPost).filter(QueuedPost.status == PostStatus.POSTED).count()
    rows = (
        db.query(PostPerformance)
        .filter((PostPerformance.impressions > 0) | (PostPerformance.likes > 0)
                | (PostPerformance.comments > 0) | (PostPerformance.shares > 0))
        .all()
    )
    return {
        "posted": posted,
        "recorded": len(rows),
        "impressions": sum(r.impressions or 0 for r in rows),
        "reactions": sum((r.likes or 0) + (r.comments or 0) + (r.shares or 0) for r in rows),
    }


def _greeting(now: datetime) -> str:
    return "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 18 else "Good evening"


@router.get("/", response_class=HTMLResponse)
def home_page(request: Request, db: Session = Depends(get_db)):
    stats = PostQueue(db).get_stats()
    token = TokenManager(db).get_token_status()
    brand = brand_status()
    now = local_now()
    slot_count = db.query(ContentCalendar).filter(ContentCalendar.is_active == True).count()  # noqa: E712

    queued = (
        db.query(QueuedPost)
        .filter(QueuedPost.status == PostStatus.QUEUED)
        .order_by(QueuedPost.quality_score.is_(None), QueuedPost.quality_score.desc(), QueuedPost.created_at.desc())
        .limit(4)
        .all()
    )
    review = []
    for p in queued:
        report = json.loads(p.quality_report) if p.quality_report else None
        review.append({
            "id": p.id, "hook": first_line(p.content), "template": plain_template(p.template_name),
            "quality": report, "virality": p.virality_score, "reach": reach_word(p.virality_score),
        })

    scheduled = (
        db.query(QueuedPost)
        .filter(QueuedPost.status == PostStatus.SCHEDULED, QueuedPost.scheduled_time.isnot(None))
        .order_by(QueuedPost.scheduled_time)
        .limit(3)
        .all()
    )
    upcoming = [{"when": fmt_local(_local(p.scheduled_time)), "hook": first_line(p.content, 90), "id": p.id}
                for p in scheduled]
    slots = [fmt_local(s) for s in next_slots(db, 3)]

    week_ago = datetime.utcnow() - timedelta(days=7)
    published_week = (
        db.query(QueuedPost)
        .filter(QueuedPost.status == PostStatus.POSTED, QueuedPost.posted_at >= week_ago)
        .count()
    )
    published_prev_week = (
        db.query(QueuedPost)
        .filter(QueuedPost.status == PostStatus.POSTED,
                QueuedPost.posted_at >= week_ago - timedelta(days=7),
                QueuedPost.posted_at < week_ago)
        .count()
    )
    weeks = weekly_published(db)
    results = results_summary(db)
    failed = stats.get("failed", 0)
    ever_approved = sum(stats.get(k, 0) for k in ("approved", "scheduled", "posted"))

    checklist = [
        {"title": "Connect Claude", "done": bool(settings.ANTHROPIC_API_KEY),
         "desc": "Add ANTHROPIC_API_KEY to the .env file so the app can write drafts.",
         "href": None, "cta": None},
        {"title": "Describe your brand voice", "done": brand["filled"],
         "desc": f"{brand['percent']}% done — drafts sound like you once this is filled in.",
         "href": "/brand", "cta": "Open Brand Voice"},
        {"title": "Connect LinkedIn", "done": bool(token.get("authenticated")),
         "desc": "Needed to publish posts from the app.", "href": "/auth/login", "cta": "Connect"},
        {"title": "Posting schedule", "done": slot_count > 0,
         "desc": f"{slot_count} weekly posting slots ({settings.POSTING_TIMEZONE}).", "href": "/schedule", "cta": "View"},
        {"title": "Approve your first post", "done": ever_approved > 0,
         "desc": "Review a draft in the Queue and approve it.", "href": "/queue", "cta": "Open Queue"},
    ]

    from engagement import followups, publisher
    engage = publisher.status(db)
    engage["followups"] = len(followups.due_followups(db))

    identity = author_identity()
    first_name = identity["name"].split()[0] if identity["name"] else ""
    return render(
        request, "home.html", "home", db,
        greeting=_greeting(now), first_name=first_name, today=f"{now:%A, %B} {now.day}",
        stats=stats, review=review, upcoming=upcoming, slots=slots, published_week=published_week,
        published_prev_week=published_prev_week, weeks=weeks, results=results,
        failed=failed, checklist=checklist, checklist_done=sum(1 for c in checklist if c["done"]),
        usage=llm.usage_summary(30), brand=brand, posts_per_day=settings.POSTS_PER_DAY, engage=engage,
    )
