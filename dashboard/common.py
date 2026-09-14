"""Shared helpers for dashboard routers: templates, page rendering, datetimes."""

import time
from datetime import date, datetime, timezone

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from config import settings
from utils.timeutil import local_now, posting_tz  # noqa: F401  (re-exported)

templates = Jinja2Templates(directory="dashboard/templates")

templates.env.globals["posting_timezone"] = settings.POSTING_TIMEZONE
# Changes on every restart, so browsers load fresh CSS/JS after an update instead of a cached copy.
templates.env.globals["asset_version"] = str(int(time.time()))


def to_iso(value) -> str | None:
    """Serialize a datetime for the browser as an explicit UTC instant.

    Naive datetimes in the DB are UTC (datetime.utcnow()). Returning them with a
    trailing 'Z' stops browsers from misreading them as local time.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def parse_client_dt(value: str) -> datetime:
    """Parse a datetime sent by the browser into naive UTC for storage.

    Accepts offset-aware ISO strings ("2026-09-15T09:00:00-04:00" or "...Z").
    Naive strings are interpreted in POSTING_TIMEZONE (the wall-clock time the
    user picked), never as UTC. Raises ValueError on bad input.
    """
    raw = (value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=posting_tz())
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _icon(path: str) -> str:
    return (f'<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" '
            f'stroke-linejoin="round" stroke-width="1.5" d="{path}"/></svg>')


ICONS = {
    "idea": _icon("M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"),
    "studio": _icon("M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"),
    "plan": _icon("M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"),
    "engage": _icon("M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"),
    "profile": _icon("M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"),
}

# Sidebar sections that grow as features are added (Create / Engage / Setup extras).
NAV_CREATE = [
    {"href": "/studio", "label": "Studio", "pages": ["studio"], "icon": ICONS["studio"]},
    {"href": "/plan", "label": "Plan", "pages": ["plan"], "icon": ICONS["plan"]},
    {"href": "/idea", "label": "Idea Lab", "pages": ["idea"], "icon": ICONS["idea"]},
]
NAV_ENGAGE = [
    {"href": "/engage", "label": "Engage", "pages": ["engage"], "icon": ICONS["engage"]},
]
NAV_SETUP = [
    {"href": "/profile-optimizer", "label": "Profile Optimizer", "pages": ["profile"], "icon": ICONS["profile"]},
]


def render(request: Request, name: str, page: str, db: Session | None = None, **ctx):
    """Render a dashboard page with the shared context every page needs."""
    from auth.token_manager import TokenManager
    from content.brand import author_identity, brand_status
    from database.engine import SessionLocal
    from database.models import PostStatus, QueuedPost

    own_session = db is None
    session = db or SessionLocal()
    try:
        auth_status = TokenManager(session).get_token_status()
        queued = session.query(QueuedPost).filter(QueuedPost.status == PostStatus.QUEUED).count()
    finally:
        if own_session:
            session.close()

    identity = author_identity()
    headline = " · ".join(x for x in (identity["role"], identity["company"]) if x)
    context = {
        "page": page,
        "auth_status": auth_status,
        "posting_timezone": settings.POSTING_TIMEZONE,
        "autoresearch_enabled": settings.AUTORESEARCH_ENABLED,
        "login_enabled": bool(settings.DASHBOARD_PASSWORD),
        "nav_counts": {"queue": queued, "brand_filled": brand_status()["filled"]},
        "nav_create": NAV_CREATE,
        "nav_engage": NAV_ENGAGE,
        "nav_setup": NAV_SETUP,
        "author_name": identity["name"] or "You",
        "author_headline": headline,
    }
    context.update(ctx)
    return templates.TemplateResponse(request, name, context)
