"""Profile Optimizer page: paste your profile, get a scorecard and rewrites."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import llm
from config import settings
from dashboard.common import render
from database.engine import get_db
from studio.base import recent_runs, run_tool
from studio.profile import optimize_profile

router = APIRouter(tags=["profile"])


class ProfileBody(BaseModel):
    headline: str = Field("", max_length=400)
    about: str = Field("", max_length=4000)
    experience: str = Field("", max_length=6000)
    skills: str = Field("", max_length=1500)
    featured: str = Field("", max_length=1500)
    profile_url: str = Field("", max_length=300)
    recommendations: int | None = Field(None, ge=0, le=1000)
    has_banner: bool = False
    has_photo: bool = False


@router.get("/profile-optimizer", response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    last = next((r for r in recent_runs(db, "profile", 5) if r["ok"]), None)
    return render(request, "profile.html", "profile", db,
                  last_input=(last or {}).get("input") or {}, last_output=(last or {}).get("output"),
                  profile_url=settings.LINKEDIN_PROFILE_URL)


@router.post("/api/profile-optimizer")
def profile_review(body: ProfileBody, db: Session = Depends(get_db)):
    data = body.model_dump()
    if not data["headline"].strip() and not data["about"].strip():
        return JSONResponse({"error": "Paste at least your headline or your About section"}, status_code=400)
    try:
        return run_tool(db, "profile", data, lambda: optimize_profile(data))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except llm.LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=503 if isinstance(e, llm.LLMNotConfigured) else 502)
