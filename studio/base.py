"""Shared plumbing for Studio tools: every run is recorded so failures are visible later."""

import json
import logging
from typing import Any, Callable

from sqlalchemy.orm import Session

import llm
from database.models import StudioRun

logger = logging.getLogger(__name__)
MAX_STORED = 20000


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:MAX_STORED]


def _load(text: str | None):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


def run_tool(db: Session, tool: str, inputs: dict, fn: Callable[[], dict]) -> dict:
    """Run a Studio tool, storing its input and output (or error) as a StudioRun."""
    run = StudioRun(tool=tool, input_json=_dump(inputs))
    try:
        output = fn()
    except Exception as e:
        if not isinstance(e, (llm.LLMError, ValueError)):
            logger.exception("Studio tool %s failed", tool)
        run.error = str(e)[:1000] or type(e).__name__
        db.add(run)
        db.commit()
        raise
    run.output_json = _dump(output)
    db.add(run)
    db.commit()
    return {**output, "run_id": run.id}


def recent_runs(db: Session, tool: str | None = None, limit: int = 10) -> list[dict]:
    query = db.query(StudioRun)
    if tool:
        query = query.filter(StudioRun.tool == tool)
    rows = query.order_by(StudioRun.created_at.desc(), StudioRun.id.desc()).limit(limit).all()
    return [{"id": r.id, "tool": r.tool, "ok": not r.error, "error": r.error,
             "input": _load(r.input_json), "output": _load(r.output_json), "created_at": r.created_at}
            for r in rows]
