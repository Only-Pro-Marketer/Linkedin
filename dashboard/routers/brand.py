"""Brand Voice: a guided editor for soul/soul.md."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import llm
from content.brand import MAX_SECTION_CHARS, brand_status, editor_sections, parse_document, save_sections, soul_text
from dashboard.common import render
from database.engine import get_db

router = APIRouter(tags=["brand"])


class BrandSave(BaseModel):
    sections: dict[str, str]


@router.get("/brand", response_class=HTMLResponse)
def brand_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "brand.html", "brand", db, editor=editor_sections(), status=brand_status())


@router.get("/api/brand")
def brand_get():
    return {"sections": editor_sections(), "status": brand_status()}


@router.post("/api/brand")
def brand_save(body: BrandSave):
    _, sections = parse_document(soul_text())
    allowed = {t for t, _ in sections} | {s["title"] for s in editor_sections()["guided"]}
    unknown = [t for t in body.sections if t not in allowed]
    if unknown:
        return JSONResponse({"error": f"Unknown section: {unknown[0]}"}, status_code=400)
    too_long = [t for t, b in body.sections.items() if len(b) > MAX_SECTION_CHARS]
    if too_long:
        return JSONResponse({"error": f"“{too_long[0]}” is too long (max {MAX_SECTION_CHARS:,} characters)"},
                            status_code=400)
    save_sections(body.sections)
    return {"status": brand_status(), "sections": editor_sections()}


class LearnVoiceBody(BaseModel):
    text: str = Field("", max_length=40000)


@router.post("/api/brand/learn-voice")
def brand_learn_voice(body: LearnVoiceBody, db: Session = Depends(get_db)):
    """Suggest voice sections from the user's own posts. Nothing is saved here."""
    from studio import voice
    from studio.base import run_tool

    samples = voice.split_samples(body.text)
    try:
        return run_tool(db, "voice", {"samples": len(samples), "chars": len(body.text)},
                        lambda: voice.learn_voice(samples))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except llm.LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=503 if isinstance(e, llm.LLMNotConfigured) else 502)
