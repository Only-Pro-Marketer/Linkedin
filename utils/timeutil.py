"""Timezone helpers. The DB stores naive UTC; the user thinks in POSTING_TIMEZONE."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from config import settings


def posting_tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.POSTING_TIMEZONE)
    except Exception:
        return ZoneInfo("America/Toronto")


def local_now() -> datetime:
    return datetime.now(posting_tz())


def local_day_bounds_utc(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Start/end of the current local day, as naive UTC datetimes."""
    tz = posting_tz()
    now_local = (now.replace(tzinfo=timezone.utc) if now and now.tzinfo is None else now or datetime.now(timezone.utc)).astimezone(tz)
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    to_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)  # noqa: E731
    return to_utc(start_local), to_utc(end_local)
