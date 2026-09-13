"""Plan: a week of posts across the user's pillars, drafted into the Queue on demand."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import llm
from content.brand import get_pillars
from content.templates.formulas import BY_ID, FORMULAS
from dashboard.common import render
from database.engine import get_db
from database.models import ContentPlanItem
from studio import planner
from studio.base import run_tool
from studio.writer import GOAL_INFO

router = APIRouter(tags=["plan"])


class PlanBody(BaseModel):
    count: int = Field(4, ge=planner.MIN_POSTS, le=planner.MAX_POSTS)
    focus: str = Field("", max_length=1000)


class ItemUpdate(BaseModel):
    topic: str | None = Field(None, max_length=1000)
    angle: str | None = Field(None, max_length=1000)
    goal: Literal["comments", "reposts", "likes", "saves"] | None = None
    formula_id: str | None = Field(None, max_length=10)


def _error(e: Exception) -> JSONResponse:
    code = 503 if isinstance(e, llm.LLMNotConfigured) else 502 if isinstance(e, llm.LLMError) else 400
    return JSONResponse({"error": str(e)}, status_code=code)


def _item(db: Session, item_id: int) -> ContentPlanItem | None:
    return db.get(ContentPlanItem, item_id)


@router.get("/plan", response_class=HTMLResponse)
def plan_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "plan.html", "plan", db, plan=planner.plan_dict(planner.current_plan(db)),
                  pillars=get_pillars(), fallback_pillars=planner.FALLBACK_PILLARS, goals=GOAL_INFO,
                  formula_names={f.id: f.name for f in FORMULAS})


@router.get("/api/plan/current")
def plan_current(db: Session = Depends(get_db)):
    return {"plan": planner.plan_dict(planner.current_plan(db))}


@router.post("/api/plan/week")
def plan_week(body: PlanBody, db: Session = Depends(get_db)):
    try:
        return run_tool(db, "plan", body.model_dump(),
                        lambda: {"plan": planner.plan_dict(planner.plan_week(db, body.count, body.focus))})
    except (llm.LLMError, ValueError) as e:
        return _error(e)


@router.post("/api/plan/items/{item_id}/draft")
def plan_item_draft(item_id: int, db: Session = Depends(get_db)):
    item = _item(db, item_id)
    if not item:
        return JSONResponse({"error": "Not found"}, status_code=404)
    try:
        post = planner.draft_item(db, item)
    except (llm.LLMError, ValueError) as e:
        if isinstance(e, llm.LLMError):
            item.error = str(e)[:500]
            db.commit()
        return _error(e)
    return {"item": planner.item_dict(item), "post_id": post.id, "quality_score": post.quality_score}


@router.post("/api/plan/items/{item_id}/skip")
def plan_item_skip(item_id: int, db: Session = Depends(get_db)):
    item = _item(db, item_id)
    if not item:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if item.status == "drafted":
        return JSONResponse({"error": "Already drafted. Reject it in the Queue instead."}, status_code=400)
    item.status = "planned" if item.status == "skipped" else "skipped"
    db.commit()
    return {"item": planner.item_dict(item)}


@router.post("/api/plan/items/{item_id}")
def plan_item_update(item_id: int, body: ItemUpdate, db: Session = Depends(get_db)):
    item = _item(db, item_id)
    if not item:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if item.status == "drafted":
        return JSONResponse({"error": "Already drafted. Edit the post in the Queue."}, status_code=400)
    if body.formula_id is not None and body.formula_id.upper() not in BY_ID:
        return JSONResponse({"error": "Unknown formula"}, status_code=400)
    for field in ("topic", "angle", "goal"):
        value = getattr(body, field)
        if value is not None:
            setattr(item, field, value.strip() if isinstance(value, str) else value)
    if body.formula_id is not None:
        item.formula_id = body.formula_id.upper()
    db.commit()
    return {"item": planner.item_dict(item)}
