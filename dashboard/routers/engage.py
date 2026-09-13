"""Engage: comment on other people's posts and reply to comments on yours."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import llm
from config import settings
from dashboard.common import render, to_iso
from database.engine import get_db
from database.models import EngagementDraft
from engagement import comment_drafter, followups, publisher, reply_handler
from linkedin.url_parser import parse_linkedin_url

router = APIRouter(tags=["engage"])

Reaction = Literal["", "LIKE", "PRAISE", "EMPATHY", "INTEREST", "APPRECIATION", "ENTERTAINMENT"]
GROUPS = {
    "pending": ("approved", "publishing"),
    "needs_you": publisher.NEEDS_YOU,
    "done": ("published", "skipped"),
    "drafts": ("draft",),
}


class CommentDraftBody(BaseModel):
    post_url: str = Field("", max_length=1000)
    post_text: str = Field("", max_length=8000)
    author: str = Field("", max_length=200)
    competitor_post_id: int | None = None


class ParseBody(BaseModel):
    comments_text: str = Field("", max_length=50000)


class FetchBody(BaseModel):
    post_url: str = Field("", max_length=1000)


class ReplyItem(BaseModel):
    author: str = Field("", max_length=200)
    text: str = Field(..., max_length=3000)
    comment_urn: str | None = Field(None, max_length=300)
    reply_urn: str | None = Field(None, max_length=300)


class ReplyDraftBody(BaseModel):
    post_url: str = Field("", max_length=1000)
    post_text: str = Field("", max_length=8000)
    comments: list[ReplyItem] = Field(default_factory=list, max_length=25)


class ApproveBody(BaseModel):
    text: str = Field("", max_length=publisher.MAX_COMMENT_CHARS)
    reaction: Reaction | None = None
    template_code: str | None = Field(None, max_length=20)


class BatchItem(ApproveBody):
    id: int


class BatchBody(BaseModel):
    items: list[BatchItem] = Field(default_factory=list, max_length=50)


def _json(raw, default):
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def draft_dict(d: EngagementDraft) -> dict:
    options = _json(d.variants, [])
    return {
        "id": d.id, "kind": d.kind, "source": d.source, "status": d.status,
        "post_url": d.post_url, "post_urn": d.post_urn, "open_url": publisher.open_url(d),
        "target_author": d.target_author, "target_text": (d.target_text or "")[:1500],
        "options": options, "report": options[0].get("report") if options else None,
        "text": d.text, "template_code": d.template_code, "reaction": d.reaction or "",
        "quality_score": d.quality_score, "can_auto": publisher.can_auto_publish(d),
        "publish_after": to_iso(d.publish_after), "published_at": to_iso(d.published_at),
        "error": d.error, "linkedin_comment_urn": d.linkedin_comment_urn,
    }


def _status(db: Session) -> dict:
    s = publisher.status(db)
    s["paused_until"] = to_iso(s["paused_until"])
    s["apify"] = bool(settings.APIFY_TOKEN)
    return s


def _error(e: Exception) -> JSONResponse:
    code = 503 if isinstance(e, llm.LLMNotConfigured) else 502 if isinstance(e, llm.LLMError) else 400
    return JSONResponse({"error": str(e)}, status_code=code)


def _get(db: Session, draft_id: int) -> EngagementDraft | None:
    return db.get(EngagementDraft, draft_id)


def _not_found() -> JSONResponse:
    return JSONResponse({"error": "Not found"}, status_code=404)


def _clean_url(url: str) -> tuple[str | None, dict]:
    url = (url or "").strip()
    if not url:
        return None, {}
    parsed = parse_linkedin_url(url)
    if parsed["url_type"] == "unknown":
        raise ValueError("That doesn't look like a LinkedIn post link")
    return url, parsed


# ── Page & status ────────────────────────────────────────────

@router.get("/engage", response_class=HTMLResponse)
def engage_page(request: Request, db: Session = Depends(get_db)):
    return render(request, "engage.html", "engage", db, status=_status(db), reactions=comment_drafter.REACTIONS)


@router.get("/api/engage/status")
def engage_status(db: Session = Depends(get_db)):
    return _status(db)


@router.post("/api/engage/mode/auto")
def engage_mode_auto(db: Session = Depends(get_db)):
    publisher.reset_api_mode(db)
    return _status(db)


# ── Comment on a post ────────────────────────────────────────

@router.post("/api/engage/comment/draft")
def engage_comment_draft(body: CommentDraftBody, db: Session = Depends(get_db)):
    try:
        url, parsed = _clean_url(body.post_url)
    except ValueError as e:
        return _error(e)
    text, author = body.post_text.strip(), body.author.strip()
    if not text and url and settings.APIFY_TOKEN:
        from research import apify_linkedin
        try:
            fetched = apify_linkedin.fetch_post(url)
        except apify_linkedin.ApifyError as e:
            return JSONResponse({"error": f"{e} Paste the post's text instead."}, status_code=502)
        text, author = fetched.get("text", ""), author or fetched.get("author", "")
    try:
        result = comment_drafter.draft_comment(text, url or "", author)
    except (llm.LLMError, ValueError) as e:
        return _error(e)
    if not result["options"]:
        return JSONResponse({"error": "Claude didn't return any comment options. Try again."}, status_code=502)
    first = result["options"][0]
    d = EngagementDraft(
        kind="comment", source="target" if body.competitor_post_id else "url",
        post_url=url, post_urn=result["post_urn"] or parsed.get("post_urn"),
        target_author=author or None, target_text=text[:8000], competitor_post_id=body.competitor_post_id,
        variants=json.dumps(result["options"]), text=first["text"], template_code=first["template"] or None,
        reaction=result["reaction"], quality_score=first["report"]["score"], status="draft",
    )
    db.add(d)
    db.commit()
    return {"draft": draft_dict(d), "skip_reason": result["skip_reason"]}


# ── Reply to comments ────────────────────────────────────────

def _review(comments: list[dict]) -> dict:
    keep, dropped = reply_handler.filter_comments(comments)
    return {"comments": keep, "dropped": dropped, "can_auto": sum(1 for c in keep if c.get("comment_urn"))}


@router.post("/api/engage/replies/parse")
def engage_replies_parse(body: ParseBody):
    return _review(reply_handler.parse_pasted_comments(body.comments_text))


@router.post("/api/engage/replies/fetch")
def engage_replies_fetch(body: FetchBody):
    if not settings.APIFY_TOKEN:
        return JSONResponse({"error": "Fetching comments needs APIFY_TOKEN in .env. Paste them instead."}, status_code=400)
    try:
        url, _ = _clean_url(body.post_url)
    except ValueError as e:
        return _error(e)
    if not url:
        return JSONResponse({"error": "Add your post's link first"}, status_code=400)
    from research import apify_linkedin
    try:
        return _review(apify_linkedin.fetch_post_comments(url))
    except apify_linkedin.ApifyError as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/api/engage/replies/draft")
def engage_replies_draft(body: ReplyDraftBody, db: Session = Depends(get_db)):
    if not body.comments:
        return JSONResponse({"error": "Pick at least one comment"}, status_code=400)
    try:
        url, parsed = _clean_url(body.post_url)
    except ValueError as e:
        return _error(e)
    comments = []
    for c in body.comments:
        item = c.model_dump()
        item["comment_urn"] = reply_handler.valid_comment_urn(item["comment_urn"])
        item["reply_urn"] = reply_handler.valid_comment_urn(item["reply_urn"]) if item["comment_urn"] else None
        comments.append(item)
    try:
        drafted = reply_handler.draft_replies(body.post_text, comments)
    except llm.LLMError as e:
        return _error(e)
    drafts = []
    for r in drafted:
        option = {"template": r["template"], "template_name": r["template_name"], "text": r["reply"], "report": r["report"]}
        d = EngagementDraft(
            kind="reply", source="paste", post_url=url,
            post_urn=reply_handler.post_urn_of(r["comment_urn"]) or parsed.get("post_urn"),
            parent_comment_urn=r["comment_urn"], reply_to_urn=r["reply_urn"] or r["comment_urn"],
            target_author=r["author"] or None, target_text=r["text"], variants=json.dumps([option]),
            text=r["reply"], template_code=r["template"] or None, reaction=r["reaction"],
            quality_score=r["report"]["score"], status="draft",
        )
        db.add(d)
        drafts.append(d)
    db.commit()
    return {"drafts": [draft_dict(d) for d in drafts]}


# ── Approve / publish / manual ───────────────────────────────

def _approve(db: Session, d: EngagementDraft, body: ApproveBody):
    if body.template_code is not None:
        d.template_code = body.template_code or None
    publisher.approve(db, d, text=body.text, reaction=body.reaction)


@router.post("/api/engage/{draft_id}/approve")
def engage_approve(draft_id: int, body: ApproveBody, db: Session = Depends(get_db)):
    d = _get(db, draft_id)
    if not d:
        return _not_found()
    try:
        _approve(db, d, body)
    except ValueError as e:
        return _error(e)
    return {"draft": draft_dict(d)}


@router.post("/api/engage/approve-batch")
def engage_approve_batch(body: BatchBody, db: Session = Depends(get_db)):
    out, errors = [], []
    for item in body.items:
        d = _get(db, item.id)
        if not d:
            continue
        try:
            _approve(db, d, item)
            out.append(draft_dict(d))
        except ValueError as e:
            errors.append({"id": item.id, "error": str(e)})
    return {"drafts": out, "errors": errors}


@router.post("/api/engage/{draft_id}/publish-now")
async def engage_publish_now(draft_id: int, db: Session = Depends(get_db)):
    d = _get(db, draft_id)
    if not d:
        return _not_found()
    if d.status != "approved":
        return JSONResponse({"error": "Approve it first"}, status_code=409)
    if publisher.api_mode(db) == "manual":
        return JSONResponse({"error": "LinkedIn refused comments from this app. Post it yourself."}, status_code=409)
    if publisher.published_today(db) >= settings.ENGAGE_DAILY_CAP:
        return JSONResponse({"error": f"Daily limit reached ({settings.ENGAGE_DAILY_CAP})"}, status_code=409)
    result = await publisher.publish_item(db, d)
    return {"result": result, "draft": draft_dict(d)}


@router.post("/api/engage/{draft_id}/done")
def engage_done(draft_id: int, db: Session = Depends(get_db)):
    d = _get(db, draft_id)
    if not d:
        return _not_found()
    return {"draft": draft_dict(publisher.mark_done(db, d))}


@router.post("/api/engage/{draft_id}/skip")
def engage_skip(draft_id: int, db: Session = Depends(get_db)):
    d = _get(db, draft_id)
    if not d:
        return _not_found()
    try:
        return {"draft": draft_dict(publisher.skip(db, d))}
    except ValueError as e:
        return _error(e)


@router.post("/api/engage/{draft_id}/retry")
def engage_retry(draft_id: int, db: Session = Depends(get_db)):
    d = _get(db, draft_id)
    if not d:
        return _not_found()
    try:
        return {"draft": draft_dict(publisher.retry(db, d))}
    except ValueError as e:
        return _error(e)


@router.get("/api/engage/drafts")
def engage_drafts(group: Literal["pending", "needs_you", "done", "drafts"] = "pending",
                  db: Session = Depends(get_db)):
    rows = (db.query(EngagementDraft).filter(EngagementDraft.status.in_(GROUPS[group]))
            .order_by(EngagementDraft.updated_at.desc(), EngagementDraft.id.desc()).limit(100).all())
    return {"drafts": [draft_dict(d) for d in rows]}


# ── Follow-ups ───────────────────────────────────────────────

@router.get("/api/engage/followups")
def engage_followups(db: Session = Depends(get_db)):
    return {"items": [draft_dict(d) for d in followups.due_followups(db)]}


@router.post("/api/engage/{draft_id}/followed-up")
def engage_followed_up(draft_id: int, db: Session = Depends(get_db)):
    d = _get(db, draft_id)
    if not d:
        return _not_found()
    followups.mark_followed_up(db, d)
    return {"ok": True}
