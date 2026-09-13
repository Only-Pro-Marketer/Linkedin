"""Studio: write from a formula, repurpose long content, and learn from hooks that worked."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import llm
from content.templates.formulas import FORMULAS
from dashboard.common import render, to_iso
from database.engine import get_db
from studio import hook_lab, repurposer, writer
from studio.base import recent_runs, run_tool

router = APIRouter(tags=["studio"])

Goal = Literal["comments", "reposts", "likes", "saves"]


class FormulaQuery(BaseModel):
    goal: Goal = "comments"
    topic: str = Field("", max_length=2000)


class WriteBody(BaseModel):
    topic: str = Field("", max_length=2000)
    goal: Goal = "comments"
    formula_id: str | None = None
    notes: str = Field("", max_length=6000)


class RepurposeBody(BaseModel):
    source_text: str = Field("", max_length=repurposer.MAX_SOURCE_CHARS)
    source_type: str = "article"
    goal: Goal = "saves"


class HookBody(BaseModel):
    text: str = Field("", max_length=10000)


class HookSaveBody(BaseModel):
    hook: str = Field("", max_length=1000)
    template: str = Field("", max_length=2000)
    formula_id: str | None = None


class SaveBody(BaseModel):
    text: str = Field("", max_length=5000)
    topic: str = Field("", max_length=500)
    goal: Goal | None = None
    formula_id: str | None = None
    source: Literal["studio", "repurpose"] = "studio"


def _error(e: Exception) -> JSONResponse:
    status = 503 if isinstance(e, llm.LLMNotConfigured) else 502 if isinstance(e, llm.LLMError) else 400
    return JSONResponse({"error": str(e)}, status_code=status)


@router.get("/studio", response_class=HTMLResponse)
def studio_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "studio.html", "studio", db, goals=writer.GOAL_INFO,
                  formulas=[writer.formula_dict(f) for f in FORMULAS], source_types=repurposer.SOURCE_TYPES)


@router.post("/api/studio/formulas")
def studio_formulas(body: FormulaQuery, db: Session = Depends(get_db)):
    return {"formulas": writer.shortlist_formulas(db, body.goal, body.topic)}


@router.post("/api/studio/write")
def studio_write(body: WriteBody, db: Session = Depends(get_db)):
    if not body.topic.strip():
        return JSONResponse({"error": "Tell Studio what the post is about"}, status_code=400)
    try:
        return run_tool(db, "write", body.model_dump(),
                        lambda: writer.draft_post(db, body.topic, body.goal, body.formula_id, body.notes))
    except (llm.LLMError, ValueError) as e:
        return _error(e)


@router.post("/api/studio/repurpose")
def studio_repurpose(body: RepurposeBody, db: Session = Depends(get_db)):
    if len(body.source_text.strip()) < repurposer.MIN_SOURCE_CHARS:
        return JSONResponse({"error": f"Paste at least {repurposer.MIN_SOURCE_CHARS} characters of source material"},
                            status_code=400)
    inputs = {"source_type": body.source_type, "goal": body.goal, "chars": len(body.source_text),
              "preview": body.source_text[:300]}
    try:
        return run_tool(db, "repurpose", inputs,
                        lambda: repurposer.repurpose(body.source_text, body.source_type, body.goal))
    except (llm.LLMError, ValueError) as e:
        return _error(e)


@router.post("/api/studio/hook")
def studio_hook(body: HookBody, db: Session = Depends(get_db)):
    if not body.text.strip():
        return JSONResponse({"error": "Paste a post to analyze"}, status_code=400)
    try:
        return run_tool(db, "hook", {"text": body.text[:2000]}, lambda: hook_lab.analyze_hook(body.text))
    except (llm.LLMError, ValueError) as e:
        return _error(e)


@router.post("/api/studio/hook/save")
def studio_hook_save(body: HookSaveBody, db: Session = Depends(get_db)):
    try:
        entry = hook_lab.save_hook(db, body.hook, body.template, body.formula_id)
    except ValueError as e:
        return _error(e)
    return {"id": entry.id, "formula_id": entry.formula_id}


@router.post("/api/studio/save")
def studio_save(body: SaveBody, db: Session = Depends(get_db)):
    if not body.text.strip():
        return JSONResponse({"error": "There is no draft to save yet"}, status_code=400)
    post = writer.save_to_queue(db, body.text, topic=body.topic, goal=body.goal,
                                formula_id=body.formula_id, source=body.source)
    return {"id": post.id, "status": post.status.value, "quality_score": post.quality_score}


@router.get("/api/studio/runs")
def studio_runs(tool: str | None = None, db: Session = Depends(get_db)):
    runs = recent_runs(db, tool)
    for run in runs:
        run["created_at"] = to_iso(run["created_at"])
    return {"runs": runs}
