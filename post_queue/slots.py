"""Upcoming posting slots from the content calendar (in POSTING_TIMEZONE)."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from database.models import ContentCalendar
from utils.timeutil import local_now


def next_calendar_slots(db: Session, count: int = 3, days: int = 8) -> list[datetime]:
    """The next active calendar slots as local-aware datetimes, soonest first."""
    now = local_now()
    slots = db.query(ContentCalendar).filter(ContentCalendar.is_active == True).all()  # noqa: E712
    upcoming = []
    for offset in range(days):
        day = now + timedelta(days=offset)
        for slot in slots:
            if slot.day_of_week != day.weekday():
                continue
            try:
                hour, minute = map(int, slot.time_slot.split(":"))
            except (ValueError, AttributeError):
                continue
            when = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if when > now:
                upcoming.append(when)
    return sorted(upcoming)[:count]
