"""Settings edited from the dashboard, stored in the AppSetting table.

Secrets stay in .env. Values saved here override the matching `config.settings`
attribute at runtime, so existing code that reads `settings.X` sees them.
"""

import json
import logging
from datetime import datetime

from config import settings

logger = logging.getLogger(__name__)

# Keys the UI may change, with the type used to coerce stored strings.
EDITABLE = {
    "LINKEDIN_PROFILE_URL": str,
    "POSTS_PER_DAY": int,
    "MIN_HOURS_BETWEEN_POSTS": float,
    "MIN_QUEUE_SIZE": int,
    "AUTORESEARCH_ENABLED": bool,
    "ENGAGE_DAILY_CAP": int,
    "AUTO_REPAIR": bool,
    "FACT_CHECK_ENABLED": bool,
}


def _coerce(key: str, raw: str):
    typ = EDITABLE.get(key, str)
    if typ is bool:
        return str(raw).lower() in ("1", "true", "yes", "on")
    return typ(raw)


def get_value(db, key: str, default=None):
    from database.models import AppSetting
    row = db.get(AppSetting, key)
    return row.value if row else default


def get_json(db, key: str, default=None):
    raw = get_value(db, key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def set_value(db, key: str, value) -> None:
    from database.models import AppSetting
    stored = value if isinstance(value, str) else json.dumps(value)
    row = db.get(AppSetting, key)
    if row:
        row.value = stored
        row.updated_at = datetime.utcnow()
    else:
        db.add(AppSetting(key=key, value=stored))
    db.commit()
    if key in EDITABLE:
        setattr(settings, key, _coerce(key, stored))


def apply_overrides() -> None:
    """Load UI-edited values into `settings` at startup."""
    from database.engine import SessionLocal
    from database.models import AppSetting

    db = SessionLocal()
    try:
        for row in db.query(AppSetting).filter(AppSetting.key.in_(list(EDITABLE))).all():
            try:
                setattr(settings, row.key, _coerce(row.key, row.value))
            except (TypeError, ValueError):
                logger.warning("Ignoring invalid stored setting %s=%r", row.key, row.value)
    finally:
        db.close()
