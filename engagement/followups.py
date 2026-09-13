"""Follow-ups: comments you posted 6–48 hours ago, worth checking for replies."""

from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.models import EngagementDraft

WINDOW = (timedelta(hours=6), timedelta(hours=48))


def due_followups(db: Session, now: datetime | None = None) -> list[EngagementDraft]:
    now = now or datetime.utcnow()
    return (db.query(EngagementDraft)
            .filter(EngagementDraft.status == "published", EngagementDraft.kind == "comment",
                    or_(EngagementDraft.source.is_(None), EngagementDraft.source != "first_comment"),
                    EngagementDraft.followed_up_at.is_(None),
                    EngagementDraft.published_at <= now - WINDOW[0],
                    EngagementDraft.published_at >= now - WINDOW[1])
            .order_by(EngagementDraft.published_at)
            .all())


def mark_followed_up(db: Session, draft: EngagementDraft) -> None:
    draft.followed_up_at = datetime.utcnow()
    db.commit()
