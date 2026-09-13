"""Quality API used by the live post editor.

/check and /autofix are deterministic (no AI, safe to call on every edit);
/ai-fix makes one Claude call that fixes only the listed problems.
"""

from typing import Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import llm
from content.humanizer import audit, auto_fix

router = APIRouter(prefix="/api/quality", tags=["quality"])


class QualityRequest(BaseModel):
    text: str = Field(default="", max_length=20000)
    kind: Literal["post", "comment", "reply"] = "post"


@router.post("/check")
def quality_check(body: QualityRequest):
    return audit(body.text, body.kind)


@router.post("/autofix")
def quality_autofix(body: QualityRequest):
    text, changes = auto_fix(body.text, body.kind)
    return {"text": text, "changes": changes, "audit": audit(text, body.kind)}


@router.post("/ai-fix")
def quality_ai_fix(body: QualityRequest):
    from content.ai_fix import fix_with_ai
    from content.pipeline import prepare_text

    report = audit(body.text, body.kind)
    if not report["blockers"] and not report["warnings"]:
        return {"text": body.text, "changed": False, "audit": report}
    try:
        fixed = fix_with_ai(body.text, report, body.kind)
    except llm.LLMError as e:
        return JSONResponse({"error": str(e)}, status_code=502)
    text, new_report, _ = prepare_text(fixed, kind=body.kind)
    return {"text": text, "changed": text != body.text, "audit": new_report}
