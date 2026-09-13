"""Settings: LinkedIn connection, automation limits, posting times, AI usage."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import app_settings
import llm
from auth.token_manager import TokenManager
from config import settings
from dashboard.common import render
from database.engine import get_db
from linkedin.api_client import LinkedInAPIClient

router = APIRouter(tags=["settings"])

FIELDS = [
    {"key": "POSTS_PER_DAY", "label": "Posts per day", "type": "int", "min": 1, "max": 5,
     "help": "Hard cap on publishes per day, on every path (Post now included)."},
    {"key": "MIN_HOURS_BETWEEN_POSTS", "label": "Hours between automatic posts", "type": "float", "min": 0, "max": 24,
     "help": "Scheduled publishing waits at least this long after your last post."},
    {"key": "MIN_QUEUE_SIZE", "label": "Drafts to keep in the Queue", "type": "int", "min": 0, "max": 30,
     "help": "Automatic drafting pauses while the Queue has this many drafts."},
    {"key": "ENGAGE_DAILY_CAP", "label": "Comments and replies per day", "type": "int", "min": 0, "max": 100,
     "help": "Engage stops publishing for the day at this number."},
    {"key": "AUTO_REPAIR", "label": "Fix failing drafts with AI", "type": "bool",
     "help": "One \"Fix with AI\" pass on new drafts that fail the quality check."},
    {"key": "FACT_CHECK_ENABLED", "label": "Fact-check new drafts", "type": "bool",
     "help": "Flags claims that need a source before you approve."},
    {"key": "AUTORESEARCH_ENABLED", "label": "Autoresearch experiments", "type": "bool",
     "help": f"Claude-scored experiments. They only run once {settings.AUTORESEARCH_MIN_POSTED} real posts are published."},
]
BY_KEY = {f["key"]: f for f in FIELDS}


class SettingsBody(BaseModel):
    values: dict[str, bool | int | float | str]


def current_values() -> dict:
    return {f["key"]: getattr(settings, f["key"]) for f in FIELDS}


def coerce(field: dict, value):
    label = field["label"]
    if field["type"] == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError(f"{label} must be on or off")
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    try:
        number = int(value) if field["type"] == "int" else float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number") from None
    if not field["min"] <= number <= field["max"]:
        raise ValueError(f"{label} must be between {field['min']} and {field['max']}")
    return number


def capabilities(token_status: dict) -> list[dict]:
    scopes = set(token_status.get("scopes") or [])
    connected = bool(token_status.get("authenticated"))
    return [
        {"label": "Publish posts", "ok": connected and "w_member_social" in scopes,
         "note": "Needs the w_member_social permission."},
        {"label": "Comment and react (Engage)", "ok": connected and "w_member_social" in scopes,
         "note": "Same permission. If LinkedIn still refuses, Engage switches to Copy + Open."},
        {"label": "Read post stats automatically", "ok": connected and "r_member_social" in scopes,
         "note": "Needs r_member_social, which LinkedIn must approve. Without it, add stats by hand in History."},
    ]


def background_jobs() -> list[dict]:
    s = settings
    apify = bool(s.APIFY_TOKEN)
    return [
        {"name": "Research topics", "when": f"Every {s.RESEARCH_INTERVAL_HOURS} h"},
        {"name": "Write drafts", "when": f"Every {s.GENERATION_INTERVAL_HOURS} h, while the Queue has under {s.MIN_QUEUE_SIZE}"},
        {"name": "Publish approved posts", "when": "Every 5 min, at your posting times"},
        {"name": "Publish approved comments", "when": "Every minute, one at a time"},
        {"name": "LinkedIn login check", "when": "Daily at midnight"},
        {"name": "Post stats", "when": "Daily at 7:30 (needs r_member_social)"},
        {"name": "Competitor posts", "when": f"Daily at {s.COMPETITOR_SCRAPE_HOUR}:00"
         if s.COMPETITOR_SCRAPE_ENABLED and apify else "Off (needs APIFY_TOKEN)"},
        {"name": "Your own posts", "when": f"Daily at {s.PROFILE_SCRAPE_HOUR}:00"
         if s.PROFILE_SCRAPE_ENABLED and apify else "Off (needs APIFY_TOKEN)"},
        {"name": "Learnings", "when": "Daily at 8:30" if s.LEARNING_ANALYSIS_ENABLED else "Off"},
        {"name": "Autoresearch", "when": f"Every {s.AUTORESEARCH_INTERVAL_HOURS} h" if s.AUTORESEARCH_ENABLED else "Off"},
    ]


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    token = TokenManager(db).get_token_status()
    return render(request, "settings.html", "settings", db, fields=FIELDS, values=current_values(),
                  capabilities=capabilities(token), jobs=background_jobs(),
                  scheduler_enabled=settings.SCHEDULER_ENABLED, usage=llm.usage_summary(30),
                  usage_features=llm.usage_by_feature(30), apify=bool(settings.APIFY_TOKEN),
                  model=settings.CLAUDE_MODEL, has_key=bool(settings.ANTHROPIC_API_KEY))


@router.post("/api/settings")
def save_settings(body: SettingsBody, db: Session = Depends(get_db)):
    clean = {}
    for key, value in body.values.items():
        field = BY_KEY.get(key)
        if not field:
            return JSONResponse({"error": f"{key} can't be changed here"}, status_code=400)
        try:
            clean[key] = coerce(field, value)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
    for key, value in clean.items():
        app_settings.set_value(db, key, str(value).lower() if isinstance(value, bool) else str(value))
    return {"values": current_values()}


@router.get("/api/usage")
def usage(days: int = 30):
    days = max(1, min(days, 365))
    return {"summary": llm.usage_summary(days), "features": llm.usage_by_feature(days)}


@router.post("/api/linkedin/test")
async def linkedin_test(db: Session = Depends(get_db)):
    """Check that the saved login still works, and say who it belongs to."""
    token = TokenManager(db).get_valid_access_token()
    if not token:
        return {"ok": False, "message": "LinkedIn isn't connected."}
    result = await LinkedInAPIClient(token).userinfo()
    code = result["status_code"]
    if code == 200:
        name = result["body"].get("name") or "your account"
        return {"ok": True, "message": f"Working. Connected as {name}."}
    if code == 401:
        return {"ok": False, "message": "LinkedIn rejected the saved login. Reconnect to fix it."}
    if code is None:
        return {"ok": False, "message": "Couldn't reach LinkedIn. Check your internet connection."}
    return {"ok": False, "message": f"LinkedIn answered {code}. Try reconnecting."}
