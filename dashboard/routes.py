"""Dashboard routes — pages and JSON API endpoints."""

from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import func, Integer
from sqlalchemy.orm import Session

from auth.token_manager import TokenManager
from config import settings
from content.generator import ContentGenerator
from database.engine import get_db
from database.models import Competitor, CompetitorPost, ContentCalendar, PostPerformance, PostStatus, QueuedPost, ResearchItem
from linkedin.poster import LinkedInPoster
from post_queue.post_queue import PostQueue

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="dashboard/templates")


# ── Pydantic models for request bodies ────────────────────────

class ApproveRequest(BaseModel):
    edited_content: str | None = None
    scheduled_time: str | None = None  # ISO format


class RejectRequest(BaseModel):
    reason: str = ""
    categories: list[str] = []  # RejectionReason values: hook_too_weak, too_generic, etc.


class EditRequest(BaseModel):
    content: str


class GenerateRequest(BaseModel):
    count: int = 5
    template_name: str | None = None
    topic: str = ""
    tone: str = "authoritative"


class BulkActionRequest(BaseModel):
    post_ids: list[int]
    reason: str = ""


class CalendarSlotRequest(BaseModel):
    day_of_week: int  # 0=Monday, 6=Sunday
    time_slot: str  # "08:30"
    is_active: bool = True
    preferred_template_type: str | None = None
    preferred_tone: str | None = None


class ScheduleRequest(BaseModel):
    scheduled_time: str  # ISO format, required


class RegenerateRequest(BaseModel):
    feedback: str = ""


class ResearchBulkActionRequest(BaseModel):
    item_ids: list[int]


class ManualResearchItemCreate(BaseModel):
    topic: str
    title: str = ""
    content: str = ""
    url: str = ""
    category: str = ""
    region: str = ""
    relevance_score: float = 0.7


class UpdateNotesRequest(BaseModel):
    notes: str


class CompetitorCreate(BaseModel):
    name: str
    linkedin_url: str = ""
    niche: str = ""
    notes: str = ""


class CompetitorPostCreate(BaseModel):
    content: str
    post_url: str = ""
    post_date: str | None = None
    likes: int = 0
    comments: int = 0
    shares: int = 0
    hook_style: str = ""
    content_format: str = ""
    topic: str = ""
    key_takeaway: str = ""
    why_it_works: str = ""


class IdeaRequest(BaseModel):
    idea: str
    variants: list[str] = ["actionable"]
    formats: list[str] = ["concise"]
    tones: list[str] = ["friendly"]
    angles: list[str] = ["story"]
    structures: list[str] = ["AIDA"]


# ── Page routes (HTML) ────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request, db: Session = Depends(get_db)):
    pq = PostQueue(db)
    tm = TokenManager(db)
    stats = pq.get_stats()
    auth_status = tm.get_token_status()
    recent_posted = pq.get_posted(limit=5)
    return templates.TemplateResponse(
        "queue.html",
        {
            "request": request,
            "stats": stats,
            "auth_status": auth_status,
            "recent_posted": recent_posted,
            "page": "queue",
        },
    )


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, db: Session = Depends(get_db)):
    pq = PostQueue(db)
    stats = pq.get_stats()
    return templates.TemplateResponse(
        "history.html",
        {"request": request, "stats": stats, "page": "history"},
    )


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, db: Session = Depends(get_db)):
    tm = TokenManager(db)
    auth_status = tm.get_token_status()
    return templates.TemplateResponse(
        "analytics.html",
        {"request": request, "auth_status": auth_status, "page": "analytics"},
    )


@router.get("/learnings", response_class=HTMLResponse)
async def learnings_page(request: Request, db: Session = Depends(get_db)):
    tm = TokenManager(db)
    auth_status = tm.get_token_status()
    return templates.TemplateResponse(
        "learnings.html",
        {"request": request, "auth_status": auth_status, "page": "learnings"},
    )


@router.get("/competitors", response_class=HTMLResponse)
async def competitors_page(request: Request, db: Session = Depends(get_db)):
    tm = TokenManager(db)
    auth_status = tm.get_token_status()
    return templates.TemplateResponse(
        "competitors.html",
        {"request": request, "auth_status": auth_status, "page": "competitors"},
    )


@router.get("/competitors/{competitor_id}", response_class=HTMLResponse)
async def competitor_detail_page(competitor_id: int, request: Request, db: Session = Depends(get_db)):
    comp = db.query(Competitor).get(competitor_id)
    if not comp:
        return HTMLResponse("<h1>Competitor not found</h1>", status_code=404)
    tm = TokenManager(db)
    auth_status = tm.get_token_status()
    return templates.TemplateResponse(
        "competitor_detail.html",
        {"request": request, "auth_status": auth_status, "page": "competitors", "competitor_id": competitor_id},
    )


@router.get("/research", response_class=HTMLResponse)
async def research_page(request: Request, db: Session = Depends(get_db)):
    tm = TokenManager(db)
    auth_status = tm.get_token_status()
    return templates.TemplateResponse(
        "research.html",
        {"request": request, "auth_status": auth_status, "page": "research"},
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    tm = TokenManager(db)
    auth_status = tm.get_token_status()
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "auth_status": auth_status, "page": "settings"},
    )


@router.get("/idea", response_class=HTMLResponse)
async def idea_page(request: Request, db: Session = Depends(get_db)):
    tm = TokenManager(db)
    auth_status = tm.get_token_status()
    return templates.TemplateResponse(
        "idea.html",
        {"request": request, "auth_status": auth_status, "page": "idea"},
    )


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_page(request: Request, db: Session = Depends(get_db)):
    pq = PostQueue(db)
    stats = pq.get_stats()
    return templates.TemplateResponse(
        "schedule.html",
        {"request": request, "stats": stats, "page": "schedule"},
    )


# ── API routes (JSON) ────────────────────────────────────────

@router.get("/api/queue")
async def api_get_queue(db: Session = Depends(get_db)):
    pq = PostQueue(db)
    posts = pq.get_queued()
    return [
        {
            "id": p.id,
            "content": p.content,
            "hook": p.hook,
            "hook_type": p.hook_type,
            "body_format": p.body_format,
            "template_name": p.template_name,
            "topic": p.topic,
            "word_count": p.word_count,
            "char_count": len(p.content) if p.content else 0,
            "newline_count": p.content.count("\n") if p.content else 0,
            "status": p.status.value,
            "has_image": p.has_image or False,
            "image_path": p.image_path,
            "has_video": p.has_video or False,
            "video_path": p.video_path,
            "media_type": p.media_type or "none",
            "video_source": p.video_source,
            "fact_check_status": p.fact_check_status or "not_checked",
            "fact_check_notes": p.fact_check_notes,
            "virality_score": p.virality_score,
            "virality_breakdown": p.virality_breakdown,
            "virality_performance": p.virality_performance,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in posts
    ]


@router.get("/api/stats")
async def api_get_stats(db: Session = Depends(get_db)):
    pq = PostQueue(db)
    return pq.get_stats()


@router.post("/api/queue/{post_id}/approve")
async def api_approve(post_id: int, body: ApproveRequest, db: Session = Depends(get_db)):
    pq = PostQueue(db)
    scheduled_time = None
    if body.scheduled_time:
        try:
            scheduled_time = datetime.fromisoformat(body.scheduled_time)
        except ValueError:
            return JSONResponse({"error": "Invalid datetime format"}, status_code=400)

    post = pq.approve(post_id, edited_content=body.edited_content, scheduled_time=scheduled_time)
    if not post:
        return JSONResponse({"error": "Post not found or cannot be approved"}, status_code=404)
    return {"status": "approved", "id": post.id, "post_status": post.status.value}


@router.post("/api/queue/{post_id}/reject")
async def api_reject(post_id: int, body: RejectRequest, db: Session = Depends(get_db)):
    pq = PostQueue(db)
    post = pq.reject(post_id, reason=body.reason)
    if not post:
        return JSONResponse({"error": "Post not found or cannot be rejected"}, status_code=404)
    # Store structured rejection categories for the learning system
    if body.categories:
        import json
        post.rejection_categories = json.dumps(body.categories)
        db.commit()
    return {"status": "rejected", "id": post.id}


@router.post("/api/queue/{post_id}/edit")
async def api_edit(post_id: int, body: EditRequest, db: Session = Depends(get_db)):
    pq = PostQueue(db)
    post = pq.edit_content(post_id, body.content)
    if not post:
        return JSONResponse({"error": "Post not found or cannot be edited"}, status_code=404)
    return {"status": "edited", "id": post.id, "word_count": post.word_count}


@router.post("/api/queue/{post_id}/regenerate")
async def api_regenerate(post_id: int, body: RegenerateRequest, db: Session = Depends(get_db)):
    gen = ContentGenerator(db)
    new_post = gen.regenerate(post_id, feedback=body.feedback)
    if not new_post:
        return JSONResponse({"error": "Failed to regenerate"}, status_code=500)
    return {
        "status": "regenerated",
        "new_id": new_post.id,
        "content": new_post.content,
    }


@router.post("/api/queue/bulk-approve")
async def api_bulk_approve(body: BulkActionRequest, db: Session = Depends(get_db)):
    pq = PostQueue(db)
    approved = pq.bulk_approve(body.post_ids)
    return {"status": "bulk_approved", "count": len(approved)}


@router.post("/api/queue/bulk-reject")
async def api_bulk_reject(body: BulkActionRequest, db: Session = Depends(get_db)):
    pq = PostQueue(db)
    rejected = pq.bulk_reject(body.post_ids, reason=body.reason)
    return {"status": "bulk_rejected", "count": len(rejected)}


@router.post("/api/generate")
async def api_generate(body: GenerateRequest, db: Session = Depends(get_db)):
    gen = ContentGenerator(db)
    if body.template_name or body.topic:
        post = gen.generate_single(
            template_name=body.template_name, topic=body.topic, tone=body.tone
        )
        return {"status": "generated", "count": 1 if post else 0}
    else:
        posts = gen.generate_batch(count=body.count)
        return {"status": "generated", "count": len(posts)}


@router.post("/api/post-now/{post_id}")
async def api_post_now(post_id: int, db: Session = Depends(get_db)):
    poster = LinkedInPoster(db)
    success = await poster.post_immediately(post_id)
    if success:
        return {"status": "posted", "id": post_id}
    return JSONResponse({"error": "Failed to post"}, status_code=500)


@router.post("/api/research/run")
async def api_run_research(db: Session = Depends(get_db)):
    from research.research_engine import ResearchEngine

    engine = ResearchEngine(db)
    items = engine.run_research_cycle()
    return {"status": "complete", "items_found": len(items)}


@router.get("/api/history")
async def api_get_history(
    status: str = "posted",
    limit: int = 50,
    db: Session = Depends(get_db),
):
    pq = PostQueue(db)
    if status == "approved":
        posts = pq.get_approved()
    elif status == "rejected":
        posts = pq.get_rejected(limit=limit)
    else:
        posts = pq.get_posted(limit=limit)

    return [
        {
            "id": p.id,
            "content": p.content,
            "template_name": p.template_name,
            "topic": p.topic,
            "status": p.status.value,
            "posted_at": p.posted_at.isoformat() if p.posted_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "scheduled_time": p.scheduled_time.isoformat() if p.scheduled_time else None,
            "linkedin_post_id": p.linkedin_post_id,
            "rejection_reason": p.rejection_reason,
            "has_image": p.has_image or False,
            "image_path": p.image_path,
            "has_video": p.has_video or False,
            "video_path": p.video_path,
            "media_type": p.media_type or "none",
            "word_count": p.word_count,
            "virality_score": p.virality_score,
            "virality_performance": p.virality_performance,
            "likes": p.performance.likes if p.performance else 0,
            "comments": p.performance.comments if p.performance else 0,
            "shares": p.performance.shares if p.performance else 0,
        }
        for p in posts
    ]


@router.delete("/api/queue/{post_id}")
async def api_delete_post(post_id: int, db: Session = Depends(get_db)):
    pq = PostQueue(db)
    if pq.delete_post(post_id):
        return {"status": "deleted", "id": post_id}
    return JSONResponse({"error": "Post not found"}, status_code=404)


@router.post("/api/queue/{post_id}/repost")
async def api_repost(post_id: int, db: Session = Depends(get_db)):
    """Duplicate a posted/rejected post back into the queue for reposting."""
    original = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
    if not original:
        return JSONResponse({"error": "Post not found"}, status_code=404)

    new_post = QueuedPost(
        content=original.user_edits or original.content,
        hook=original.hook,
        hook_type=original.hook_type,
        body_format=original.body_format,
        cta_type=original.cta_type,
        template_name=original.template_name,
        word_count=original.word_count,
        status=PostStatus.QUEUED,
        topic=original.topic,
        media_type=original.media_type or "none",
        image_path=original.image_path,
        image_prompt=original.image_prompt,
        has_image=original.has_image or False,
        video_path=original.video_path,
        video_prompt=original.video_prompt,
        has_video=original.has_video or False,
        virality_score=original.virality_score,
        virality_performance=original.virality_performance,
        virality_breakdown=original.virality_breakdown,
    )
    db.add(new_post)
    db.commit()
    db.refresh(new_post)
    return {"status": "requeued", "new_id": new_post.id, "original_id": post_id}


# ── Schedule API routes ──────────────────────────────────────


@router.get("/api/schedule")
async def api_get_schedule(db: Session = Depends(get_db)):
    """Return all scheduled posts and available (approved/queued) posts."""
    pq = PostQueue(db)
    scheduled = pq.get_scheduled()
    approved = pq.get_approved()
    queued = pq.get_queued()

    return {
        "scheduled": [
            {
                "id": p.id,
                "content": p.content[:150] + "..." if len(p.content) > 150 else p.content,
                "full_content": p.content,
                "template_name": p.template_name,
                "topic": p.topic,
                "status": p.status.value,
                "scheduled_time": p.scheduled_time.isoformat() if p.scheduled_time else None,
                "has_image": p.has_image or False,
                "image_path": p.image_path,
                "has_video": p.has_video or False,
                "video_path": p.video_path,
                "media_type": p.media_type or "none",
                "word_count": p.word_count,
                "virality_score": p.virality_score,
                "virality_performance": p.virality_performance,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in scheduled
        ],
        "available": [
            {
                "id": p.id,
                "content": p.content[:100] + "..." if len(p.content) > 100 else p.content,
                "template_name": p.template_name,
                "topic": p.topic,
                "status": p.status.value,
                "word_count": p.word_count,
                "virality_score": p.virality_score,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in approved + queued
        ],
    }


@router.post("/api/queue/{post_id}/schedule")
async def api_schedule_post(post_id: int, body: ScheduleRequest, db: Session = Depends(get_db)):
    """Schedule a post for a specific date/time."""
    try:
        scheduled_time = datetime.fromisoformat(body.scheduled_time)
    except ValueError:
        return JSONResponse({"error": "Invalid datetime format"}, status_code=400)

    pq = PostQueue(db)
    post = pq.schedule(post_id, scheduled_time)
    if not post:
        return JSONResponse({"error": "Post not found or cannot be scheduled"}, status_code=404)
    return {
        "status": "scheduled",
        "id": post.id,
        "scheduled_time": post.scheduled_time.isoformat(),
    }


@router.post("/api/queue/{post_id}/unschedule")
async def api_unschedule_post(post_id: int, db: Session = Depends(get_db)):
    """Remove scheduling from a post, reverting to approved status."""
    pq = PostQueue(db)
    post = pq.unschedule(post_id)
    if not post:
        return JSONResponse({"error": "Post not found or not scheduled"}, status_code=404)
    return {"status": "unscheduled", "id": post.id}


# ── Content Calendar API routes ───────────────────────────────


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@router.get("/api/calendar")
async def api_get_calendar(db: Session = Depends(get_db)):
    """Return all content calendar time slots."""
    slots = db.query(ContentCalendar).order_by(ContentCalendar.day_of_week, ContentCalendar.time_slot).all()
    return {
        "slots": [
            {
                "id": s.id,
                "day_of_week": s.day_of_week,
                "day_name": DAY_NAMES[s.day_of_week] if 0 <= s.day_of_week <= 6 else "Unknown",
                "time_slot": s.time_slot,
                "is_active": s.is_active,
                "preferred_template_type": s.preferred_template_type,
                "preferred_tone": s.preferred_tone,
            }
            for s in slots
        ],
        "timezone": settings.POSTING_TIMEZONE,
    }


@router.post("/api/calendar")
async def api_add_calendar_slot(body: CalendarSlotRequest, db: Session = Depends(get_db)):
    """Add or update a content calendar time slot."""
    if not (0 <= body.day_of_week <= 6):
        return JSONResponse({"error": "day_of_week must be 0-6"}, status_code=400)

    # Check for duplicate
    existing = (
        db.query(ContentCalendar)
        .filter(ContentCalendar.day_of_week == body.day_of_week, ContentCalendar.time_slot == body.time_slot)
        .first()
    )
    if existing:
        existing.is_active = body.is_active
        existing.preferred_template_type = body.preferred_template_type
        existing.preferred_tone = body.preferred_tone
        db.commit()
        return {"status": "updated", "id": existing.id}

    slot = ContentCalendar(
        day_of_week=body.day_of_week,
        time_slot=body.time_slot,
        is_active=body.is_active,
        preferred_template_type=body.preferred_template_type,
        preferred_tone=body.preferred_tone,
    )
    db.add(slot)
    db.commit()
    return {"status": "created", "id": slot.id}


@router.delete("/api/calendar/{slot_id}")
async def api_delete_calendar_slot(slot_id: int, db: Session = Depends(get_db)):
    """Delete a content calendar time slot."""
    slot = db.query(ContentCalendar).filter(ContentCalendar.id == slot_id).first()
    if not slot:
        return JSONResponse({"error": "Slot not found"}, status_code=404)
    db.delete(slot)
    db.commit()
    return {"status": "deleted", "id": slot_id}


@router.get("/api/next-slots")
async def api_get_next_slots(db: Session = Depends(get_db)):
    """Show when the next 5 posts will go out based on the content calendar."""
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(settings.POSTING_TIMEZONE)
    except (KeyError, Exception):
        tz = ZoneInfo("America/Toronto")

    now = datetime.now(tz)
    active_slots = (
        db.query(ContentCalendar)
        .filter(ContentCalendar.is_active == True)
        .order_by(ContentCalendar.day_of_week, ContentCalendar.time_slot)
        .all()
    )

    if not active_slots:
        return {"next_slots": [], "timezone": settings.POSTING_TIMEZONE}

    upcoming = []
    for days_ahead in range(8):  # look up to a week ahead
        check_date = now + timedelta(days=days_ahead)
        check_day = check_date.weekday()
        for slot in active_slots:
            if slot.day_of_week != check_day:
                continue
            hour, minute = map(int, slot.time_slot.split(":"))
            slot_dt = check_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if slot_dt > now:
                upcoming.append({
                    "datetime": slot_dt.isoformat(),
                    "day_name": DAY_NAMES[slot.day_of_week],
                    "time_slot": slot.time_slot,
                })
            if len(upcoming) >= 5:
                break
        if len(upcoming) >= 5:
            break

    return {"next_slots": upcoming, "timezone": settings.POSTING_TIMEZONE}


# ── Image Generation API routes ───────────────────────────────


@router.post("/api/queue/{post_id}/generate-image")
async def api_generate_image(post_id: int, db: Session = Depends(get_db)):
    """Generate an image for a queued post using Gemini (Nano Banana)."""
    try:
        from content.image_generator import ImageGenerator
        gen = ImageGenerator()
        result = gen.generate_for_post(db, post_id)
        if result.get("success"):
            return {
                "status": "generated",
                "id": post_id,
                "image_path": result.get("image_path", ""),
            }
        return JSONResponse({"error": result.get("error", "Unknown error")}, status_code=500)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Image generation failed for post %d: %s", post_id, e)
        return JSONResponse({"error": "Image generation failed"}, status_code=500)


@router.delete("/api/queue/{post_id}/image")
async def api_remove_image(post_id: int, db: Session = Depends(get_db)):
    """Remove the image from a queued post."""
    from content.image_generator import ImageGenerator
    gen = ImageGenerator()
    if gen.remove_image(db, post_id):
        return {"status": "removed", "id": post_id}
    return JSONResponse({"error": "Post not found"}, status_code=404)


@router.post("/api/queue/{post_id}/upload-image")
async def api_upload_image(post_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a custom image for a queued post."""
    import os
    import uuid

    post = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
    if not post:
        return JSONResponse({"error": "Post not found"}, status_code=404)

    # Validate file type
    allowed = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
    if file.content_type not in allowed:
        return JSONResponse({"error": "Only PNG, JPEG, WebP, and GIF images are allowed"}, status_code=400)

    # Save to static/images/generated/
    img_dir = os.path.join("dashboard", "static", "images", "generated")
    os.makedirs(img_dir, exist_ok=True)

    # Sanitize filename — strip path components to prevent path traversal
    safe_name = os.path.basename(file.filename) if file.filename else "upload.png"
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else "png"
    if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
        ext = "png"
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    filepath = os.path.join(img_dir, filename)

    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    # Remove old image if exists
    if post.image_path:
        old_path = post.image_path.lstrip("/")
        if os.path.exists(old_path):
            os.remove(old_path)

    # Update post
    web_path = f"/static/images/generated/{filename}"
    post.image_path = web_path
    post.has_image = True
    post.image_prompt = "user_upload"
    db.commit()

    return {"status": "uploaded", "id": post_id, "image_path": web_path}


# ── GIF / Video Generation API routes ─────────────────────────


class GifGenerateRequest(BaseModel):
    mode: str = "auto"  # auto, programmatic, screen_record
    gif_type: str | None = None  # data_counter, before_after, text_reveal, stat_cards
    params: dict | None = None  # mode-specific parameters


@router.post("/api/queue/{post_id}/generate-gif")
async def api_generate_gif(post_id: int, body: GifGenerateRequest = None, db: Session = Depends(get_db)):
    """Generate a GIF for a queued post.

    If no params/gif_type provided, uses AI planner to decide the best GIF
    based on the actual post content.
    """
    if body is None:
        body = GifGenerateRequest()

    try:
        from content.gif_generator import GifGenerator
        gen = GifGenerator()

        gif_params = body.params or {}
        if body.gif_type:
            gif_params["gif_type"] = body.gif_type

        if body.mode == "screen_record":
            url = gif_params.get("url")
            if not url:
                return JSONResponse({"error": "url is required for screen_record mode"}, status_code=400)
            actions = gif_params.get("actions")
            result = await gen.generate_screen_record_for_post(db, post_id, url, actions)
        elif body.mode == "auto" or (body.mode == "programmatic" and not body.gif_type):
            # No specific GIF type requested — use AI planner to choose based on post content
            result = gen.generate_for_post(db, post_id, mode="auto", gif_params=gif_params)
        else:
            result = gen.generate_for_post(db, post_id, mode=body.mode, gif_params=gif_params)

        if result.get("success"):
            return {"status": "generated", "id": post_id, "video_path": result.get("video_path", "")}
        return JSONResponse({"error": result.get("error", "Unknown error")}, status_code=500)

    except Exception as e:
        import logging
        logging.getLogger(__name__).error("GIF generation failed for post %d: %s", post_id, e)
        return JSONResponse({"error": "GIF generation failed"}, status_code=500)


@router.post("/api/queue/{post_id}/plan-gif")
async def api_plan_gif(post_id: int, db: Session = Depends(get_db)):
    """Use AI to plan the best GIF type for a post."""
    post = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
    if not post:
        return JSONResponse({"error": "Post not found"}, status_code=404)

    from content.gif_planner import plan_gif
    plan = plan_gif(post.content, post.topic or "")
    if plan:
        return {"status": "planned", "id": post_id, "plan": plan}
    return JSONResponse({"error": "Failed to generate GIF plan"}, status_code=500)


@router.delete("/api/queue/{post_id}/video")
async def api_remove_video(post_id: int, db: Session = Depends(get_db)):
    """Remove the video/GIF from a queued post."""
    from content.gif_generator import GifGenerator
    gen = GifGenerator()
    if gen.remove_video(db, post_id):
        return {"status": "removed", "id": post_id}
    return JSONResponse({"error": "Post not found"}, status_code=404)


@router.post("/api/queue/{post_id}/upload-video")
async def api_upload_video(post_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a video/GIF file and process it for a queued post."""
    import os
    import uuid

    post = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
    if not post:
        return JSONResponse({"error": "Post not found"}, status_code=404)

    allowed = {"video/mp4", "video/webm", "video/quicktime", "image/gif"}
    if file.content_type not in allowed:
        return JSONResponse({"error": "Only MP4, WebM, MOV, and GIF files are allowed"}, status_code=400)

    # Save upload to temp location
    upload_dir = os.path.join("dashboard", "static", "videos", "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "mp4"
    temp_filename = f"upload_{uuid.uuid4().hex[:12]}.{ext}"
    temp_path = os.path.join(upload_dir, temp_filename)

    contents = await file.read()
    with open(temp_path, "wb") as f:
        f.write(contents)

    # Process into optimized GIF
    try:
        from content.gif_generator import GifGenerator
        gen = GifGenerator()
        result = gen.generate_for_post(
            db, post_id, mode="upload", gif_params={"file_path": temp_path}
        )

        # Clean up temp upload
        if os.path.exists(temp_path):
            os.remove(temp_path)

        if result["success"]:
            return {"status": "uploaded", "id": post_id, "video_path": result["video_path"]}
        return JSONResponse({"error": result.get("error", "Unknown error")}, status_code=500)

    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/research/{item_id}/deep-research")
async def api_deep_research(item_id: int, db: Session = Depends(get_db)):
    """Run deep research on a research item — extract data points and take screenshots."""
    try:
        from research.deep_researcher import DeepResearcher
        researcher = DeepResearcher(db)
        result = await researcher.enrich_research_item(item_id)
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Analytics API routes ───────────────────────────────────────


@router.get("/api/analytics/overview")
async def api_analytics_overview(
    days: int = 30,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
):
    """Return overview stats for a given period (default 30 days)."""
    if start_date and end_date:
        cutoff = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date) + timedelta(days=1)
        days = (end - cutoff).days
    else:
        cutoff = datetime.utcnow() - timedelta(days=days)
        end = datetime.utcnow() + timedelta(days=1)

    # Fetch all posted posts within the period, eager-load performance
    posts = (
        db.query(QueuedPost)
        .filter(
            QueuedPost.status == PostStatus.POSTED,
            QueuedPost.posted_at >= cutoff,
            QueuedPost.posted_at < end,
        )
        .all()
    )

    total_posts = len(posts)
    total_likes = sum(p.performance.likes if p.performance else 0 for p in posts)
    total_comments = sum(p.performance.comments if p.performance else 0 for p in posts)
    total_shares = sum(p.performance.shares if p.performance else 0 for p in posts)
    total_impressions = sum(p.performance.impressions if p.performance else 0 for p in posts)

    avg_likes = round(total_likes / total_posts, 2) if total_posts else 0
    avg_comments = round(total_comments / total_posts, 2) if total_posts else 0

    total_engagements = total_likes + total_comments + total_shares
    engagement_rate = (
        round(total_engagements / total_impressions * 100, 2)
        if total_impressions
        else 0
    )

    # Best performing post by total engagement
    best_post = None
    if posts:
        best = max(
            posts,
            key=lambda p: (
                (p.performance.likes + p.performance.comments + p.performance.shares)
                if p.performance
                else 0
            ),
        )
        best_post = {
            "id": best.id,
            "content_preview": best.content[:150] + "..." if len(best.content) > 150 else best.content,
            "likes": best.performance.likes if best.performance else 0,
            "comments": best.performance.comments if best.performance else 0,
        }

    # Posting streak: consecutive days (ending today or most recent day) with >= 1 post
    posting_streak = 0
    if posts:
        post_dates = sorted({p.posted_at.date() for p in posts if p.posted_at}, reverse=True)
        if post_dates:
            current_date = post_dates[0]
            for d in post_dates:
                if d == current_date:
                    posting_streak += 1
                    current_date -= timedelta(days=1)
                else:
                    break

    return {
        "period_days": days,
        "total_posts": total_posts,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_shares": total_shares,
        "total_impressions": total_impressions,
        "avg_likes_per_post": avg_likes,
        "avg_comments_per_post": avg_comments,
        "engagement_rate": engagement_rate,
        "best_performing_post": best_post,
        "posting_streak": posting_streak,
    }


@router.get("/api/analytics/timeline")
async def api_analytics_timeline(
    days: int = 30,
    start_date: str | None = None,
    end_date: str | None = None,
    db: Session = Depends(get_db),
):
    """Return daily aggregated data for the given period."""
    if start_date and end_date:
        cutoff_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
        days = (end_dt - cutoff_dt).days
    else:
        cutoff_dt = datetime.utcnow() - timedelta(days=days)
        end_dt = datetime.utcnow() + timedelta(days=1)

    posts = (
        db.query(QueuedPost)
        .filter(
            QueuedPost.status == PostStatus.POSTED,
            QueuedPost.posted_at >= cutoff_dt,
            QueuedPost.posted_at < end_dt,
        )
        .all()
    )

    # Aggregate by date
    daily: dict[str, dict] = defaultdict(
        lambda: {"posts_count": 0, "likes": 0, "comments": 0, "shares": 0, "impressions": 0}
    )
    for p in posts:
        if not p.posted_at:
            continue
        day_key = p.posted_at.date().isoformat()
        daily[day_key]["posts_count"] += 1
        if p.performance:
            daily[day_key]["likes"] += p.performance.likes
            daily[day_key]["comments"] += p.performance.comments
            daily[day_key]["shares"] += p.performance.shares
            daily[day_key]["impressions"] += p.performance.impressions

    # Build a complete timeline (fill in zero-days)
    timeline = []
    for i in range(days):
        d = (cutoff_dt + timedelta(days=i)).date().isoformat()
        entry = daily.get(d, {"posts_count": 0, "likes": 0, "comments": 0, "shares": 0, "impressions": 0})
        timeline.append({"date": d, **entry})

    return timeline


@router.get("/api/analytics/templates")
async def api_analytics_templates(db: Session = Depends(get_db)):
    """Return template performance comparison sorted by engagement score."""
    posts = (
        db.query(QueuedPost)
        .filter(QueuedPost.status == PostStatus.POSTED)
        .all()
    )

    # Group by template name
    templates_data: dict[str, list] = defaultdict(list)
    for p in posts:
        name = p.template_name or "Unknown"
        perf = p.performance
        templates_data[name].append({
            "likes": perf.likes if perf else 0,
            "comments": perf.comments if perf else 0,
            "shares": perf.shares if perf else 0,
        })

    result = []
    for template_name, entries in templates_data.items():
        count = len(entries)
        total_likes = sum(e["likes"] for e in entries)
        total_comments = sum(e["comments"] for e in entries)
        total_shares = sum(e["shares"] for e in entries)
        total_engagement = total_likes + total_comments + total_shares
        engagement_score = round(total_engagement / count, 2) if count else 0

        result.append({
            "template_name": template_name,
            "posts_count": count,
            "avg_likes": round(total_likes / count, 2) if count else 0,
            "avg_comments": round(total_comments / count, 2) if count else 0,
            "avg_shares": round(total_shares / count, 2) if count else 0,
            "total_engagement": total_engagement,
            "engagement_score": engagement_score,
        })

    result.sort(key=lambda x: x["engagement_score"], reverse=True)
    return result


@router.get("/api/analytics/posts")
async def api_analytics_posts(limit: int = 10, offset: int = 0, db: Session = Depends(get_db)):
    """Return individual post performance sorted by posted_at descending."""
    base_query = db.query(QueuedPost).filter(QueuedPost.status == PostStatus.POSTED)
    total = base_query.count()

    posts = (
        base_query
        .order_by(QueuedPost.posted_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = []
    for p in posts:
        perf = p.performance
        likes = perf.likes if perf else 0
        comments = perf.comments if perf else 0
        shares = perf.shares if perf else 0
        impressions = perf.impressions if perf else 0
        total_eng = likes + comments + shares
        eng_score = round(total_eng / impressions * 100, 2) if impressions else 0

        items.append({
            "id": p.id,
            "content": p.content[:150] + "..." if len(p.content) > 150 else p.content,
            "template_name": p.template_name,
            "hook_type": p.hook_type,
            "posted_at": p.posted_at.isoformat() if p.posted_at else None,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "impressions": impressions,
            "engagement_score": eng_score,
        })

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/api/analytics/best-times")
async def api_analytics_best_times(db: Session = Depends(get_db)):
    """Return best posting times analysis based on historical engagement."""
    posts = (
        db.query(QueuedPost)
        .filter(
            QueuedPost.status == PostStatus.POSTED,
            QueuedPost.posted_at.isnot(None),
        )
        .all()
    )

    # Group by (hour, day_of_week)
    time_slots: dict[tuple[int, int], list[float]] = defaultdict(list)
    for p in posts:
        if not p.posted_at:
            continue
        hour = p.posted_at.hour
        day_of_week = p.posted_at.weekday()  # 0=Monday, 6=Sunday
        perf = p.performance
        engagement = (
            (perf.likes + perf.comments + perf.shares) if perf else 0
        )
        time_slots[(hour, day_of_week)].append(engagement)

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    result = []
    for (hour, dow), engagements in time_slots.items():
        avg_eng = round(sum(engagements) / len(engagements), 2)
        result.append({
            "hour": hour,
            "day_of_week": day_names[dow],
            "avg_engagement": avg_eng,
            "posts_count": len(engagements),
        })

    result.sort(key=lambda x: x["avg_engagement"], reverse=True)
    return result


@router.get("/api/analytics/growth")
async def api_analytics_growth(db: Session = Depends(get_db)):
    """Return weekly growth metrics."""
    posts = (
        db.query(QueuedPost)
        .filter(
            QueuedPost.status == PostStatus.POSTED,
            QueuedPost.posted_at.isnot(None),
        )
        .order_by(QueuedPost.posted_at.asc())
        .all()
    )

    if not posts:
        return []

    # Group by ISO week
    weeks: dict[str, list] = defaultdict(list)
    for p in posts:
        if not p.posted_at:
            continue
        # Start of the ISO week (Monday)
        week_start = p.posted_at.date() - timedelta(days=p.posted_at.weekday())
        weeks[week_start.isoformat()].append(p)

    result = []
    for week_start, week_posts in sorted(weeks.items()):
        count = len(week_posts)
        total_likes = sum(p.performance.likes if p.performance else 0 for p in week_posts)
        total_comments = sum(p.performance.comments if p.performance else 0 for p in week_posts)
        total_eng = total_likes + total_comments + sum(
            p.performance.shares if p.performance else 0 for p in week_posts
        )
        avg_engagement = round(total_eng / count, 2) if count else 0

        result.append({
            "week_start": week_start,
            "posts_count": count,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "avg_engagement": avg_engagement,
        })

    return result


@router.post("/api/analytics/refresh-engagement")
async def api_refresh_engagement(db: Session = Depends(get_db)):
    """Fetch latest engagement data from LinkedIn for all posted posts."""
    from analytics.performance_tracker import PerformanceTracker

    tracker = PerformanceTracker(db)
    updated = await tracker.fetch_engagement_from_linkedin()
    return {"status": "complete", "posts_updated": updated}


@router.post("/api/analytics/generate-sample-data")
async def api_generate_sample_data(db: Session = Depends(get_db)):
    """Generate sample performance data for testing the dashboard."""
    from analytics.performance_tracker import PerformanceTracker

    tracker = PerformanceTracker(db)
    created = tracker.create_sample_performance_data()
    return {"status": "complete", "records_created": created}


@router.post("/api/analytics/import-history")
async def api_import_post_history(db: Session = Depends(get_db)):
    """Fetch all posts from the user's LinkedIn profile and import them.

    Imports posts as POSTED status with their engagement data so they
    appear in analytics for learning and repurposing.
    """
    from auth.token_manager import TokenManager
    from linkedin.api_client import LinkedInAPIClient

    token_manager = TokenManager(db)
    access_token = token_manager.get_valid_access_token()
    if not access_token:
        return JSONResponse(
            {"error": "No valid LinkedIn access token. Please reconnect on Settings page."},
            status_code=401,
        )

    person_urn = token_manager.get_person_urn()
    if not person_urn:
        return JSONResponse(
            {"error": "No person URN. Please reconnect your LinkedIn account."},
            status_code=401,
        )

    client = LinkedInAPIClient(access_token)

    # Fetch all posts from LinkedIn
    linkedin_posts = await client.fetch_author_posts(person_urn, count=200)

    if not linkedin_posts:
        return {"status": "complete", "imported": 0, "message": "No posts found on LinkedIn"}

    # Check which post URNs we already have in the DB
    existing_urns = set(
        r[0] for r in db.query(QueuedPost.linkedin_post_id)
        .filter(QueuedPost.linkedin_post_id.isnot(None))
        .all()
    )

    imported = 0
    skipped = 0

    for lp in linkedin_posts:
        urn = lp["urn"]
        if not urn or urn in existing_urns:
            skipped += 1
            continue

        content = lp.get("content", "")
        if not content or len(content.strip()) < 20:
            skipped += 1
            continue

        # Convert LinkedIn epoch timestamp (ms) to datetime
        created_ms = lp.get("created_at", 0)
        posted_at = (
            datetime.utcfromtimestamp(created_ms / 1000)
            if created_ms
            else datetime.utcnow()
        )

        # Create a QueuedPost record for this historical post
        post = QueuedPost(
            content=content.strip(),
            hook=content.strip().split("\n")[0][:200],
            hook_type="imported",
            body_format="imported",
            cta_type="imported",
            template_name="LinkedIn Import",
            word_count=len(content.split()),
            status=PostStatus.POSTED,
            topic="imported",
            linkedin_post_id=urn,
            posted_at=posted_at,
        )
        db.add(post)
        db.flush()  # Get the ID

        # Fetch engagement for this post
        try:
            metrics = await client.fetch_post_social_counts(urn)
            perf = PostPerformance(
                post_id=post.id,
                likes=metrics.get("likes", 0),
                comments=metrics.get("comments", 0),
                shares=metrics.get("shares", 0),
                impressions=0,
                last_checked=datetime.utcnow(),
            )
            db.add(perf)
        except Exception:
            pass  # Continue even if engagement fetch fails

        imported += 1
        existing_urns.add(urn)

    db.commit()

    return {
        "status": "complete",
        "imported": imported,
        "skipped": skipped,
        "total_found": len(linkedin_posts),
    }


@router.get("/api/analytics/imported-posts")
async def api_get_imported_posts(limit: int = 50, db: Session = Depends(get_db)):
    """Get imported LinkedIn posts sorted by engagement for learning."""
    posts = (
        db.query(QueuedPost)
        .filter(
            QueuedPost.status == PostStatus.POSTED,
            QueuedPost.template_name == "LinkedIn Import",
        )
        .order_by(QueuedPost.posted_at.desc())
        .limit(limit)
        .all()
    )

    result = []
    for p in posts:
        likes = p.performance.likes if p.performance else 0
        comments = p.performance.comments if p.performance else 0
        shares = p.performance.shares if p.performance else 0
        total_eng = likes + comments * 3 + shares * 5

        result.append({
            "id": p.id,
            "content": p.content[:300] + "..." if len(p.content) > 300 else p.content,
            "full_content": p.content,
            "posted_at": p.posted_at.isoformat() if p.posted_at else None,
            "linkedin_post_id": p.linkedin_post_id,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "engagement_score": total_eng,
            "word_count": p.word_count,
        })

    # Sort by engagement score descending
    result.sort(key=lambda x: x["engagement_score"], reverse=True)
    return result


# ── Competitor Management API routes ──────────────────────────


@router.get("/api/competitors")
async def api_get_competitors(db: Session = Depends(get_db)):
    """List all competitors with their post counts and average engagement."""
    comps = db.query(Competitor).order_by(Competitor.created_at.desc()).all()

    # Single aggregation query instead of N+1 per-competitor queries
    agg = (
        db.query(
            CompetitorPost.competitor_id,
            func.count(CompetitorPost.id).label("post_count"),
            func.avg(CompetitorPost.likes).label("avg_likes"),
            func.avg(CompetitorPost.comments).label("avg_comments"),
            func.avg(CompetitorPost.shares).label("avg_shares"),
        )
        .group_by(CompetitorPost.competitor_id)
        .all()
    )
    agg_map = {
        row.competitor_id: {
            "post_count": row.post_count,
            "avg_likes": round(row.avg_likes or 0, 2),
            "avg_comments": round(row.avg_comments or 0, 2),
            "avg_shares": round(row.avg_shares or 0, 2),
        }
        for row in agg
    }

    result = []
    for c in comps:
        stats = agg_map.get(c.id, {"post_count": 0, "avg_likes": 0.0, "avg_comments": 0.0, "avg_shares": 0.0})
        result.append({
            "id": c.id,
            "name": c.name,
            "linkedin_url": c.linkedin_url,
            "linkedin_username": c.linkedin_username,
            "niche": c.niche,
            "notes": c.notes,
            "is_active": c.is_active,
            "profile_picture": c.profile_picture,
            "headline": c.headline,
            "follower_count": c.follower_count or 0,
            "total_posts_tracked": stats["post_count"],
            "avg_likes": stats["avg_likes"],
            "avg_comments": stats["avg_comments"],
            "avg_shares": stats["avg_shares"],
            "posting_frequency": c.posting_frequency,
            "last_scraped_at": c.last_scraped_at.isoformat() if c.last_scraped_at else None,
            "scrape_status": c.scrape_status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })
    return result


@router.post("/api/competitors")
async def api_create_competitor(body: CompetitorCreate, db: Session = Depends(get_db)):
    """Create a new competitor."""
    comp = Competitor(
        name=body.name,
        linkedin_url=body.linkedin_url or None,
        niche=body.niche or None,
        notes=body.notes or None,
    )
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return {
        "status": "created",
        "id": comp.id,
        "name": comp.name,
        "created_at": comp.created_at.isoformat() if comp.created_at else None,
    }


@router.put("/api/competitors/{competitor_id}")
async def api_update_competitor(competitor_id: int, body: CompetitorCreate, db: Session = Depends(get_db)):
    """Update an existing competitor."""
    comp = db.query(Competitor).get(competitor_id)
    if not comp:
        return JSONResponse({"error": "Competitor not found"}, status_code=404)
    comp.name = body.name
    comp.linkedin_url = body.linkedin_url or None
    comp.niche = body.niche or None
    comp.notes = body.notes or None
    db.commit()
    db.refresh(comp)
    return {
        "status": "updated",
        "id": comp.id,
        "name": comp.name,
        "updated_at": comp.updated_at.isoformat() if comp.updated_at else None,
    }


@router.delete("/api/competitors/{competitor_id}")
async def api_delete_competitor(competitor_id: int, db: Session = Depends(get_db)):
    """Delete a competitor and cascade-delete all their posts."""
    comp = db.query(Competitor).get(competitor_id)
    if not comp:
        return JSONResponse({"error": "Competitor not found"}, status_code=404)
    db.delete(comp)
    db.commit()
    return {"status": "deleted", "id": competitor_id}


@router.get("/api/competitors/{competitor_id}/posts")
async def api_get_competitor_posts(competitor_id: int, db: Session = Depends(get_db)):
    """Get all posts for a specific competitor, sorted by likes descending."""
    comp = db.query(Competitor).get(competitor_id)
    if not comp:
        return JSONResponse({"error": "Competitor not found"}, status_code=404)

    posts = (
        db.query(CompetitorPost)
        .filter(CompetitorPost.competitor_id == competitor_id)
        .order_by(CompetitorPost.likes.desc())
        .all()
    )

    return [
        {
            "id": p.id,
            "competitor_id": p.competitor_id,
            "content": p.content,
            "post_url": p.post_url,
            "linkedin_post_id": p.linkedin_post_id,
            "post_date": p.post_date.isoformat() if p.post_date else None,
            "likes": p.likes,
            "comments": p.comments,
            "shares": p.shares,
            "impressions": p.impressions,
            "has_image": p.has_image,
            "has_video": p.has_video,
            "image_url": p.image_url,
            "hook_style": p.hook_style,
            "content_format": p.content_format,
            "topic": p.topic,
            "key_takeaway": p.key_takeaway,
            "why_it_works": p.why_it_works,
            "how_to_recreate": p.how_to_recreate,
            "ai_analyzed": p.ai_analyzed,
            "is_saved": p.is_saved,
            "recreated": p.recreated,
            "source": p.source,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in posts
    ]


@router.post("/api/competitors/{competitor_id}/posts")
async def api_create_competitor_post(competitor_id: int, body: CompetitorPostCreate, db: Session = Depends(get_db)):
    """Add a post for a specific competitor."""
    comp = db.query(Competitor).get(competitor_id)
    if not comp:
        return JSONResponse({"error": "Competitor not found"}, status_code=404)

    # Parse post_date if provided
    post_date = None
    if body.post_date:
        try:
            post_date = datetime.fromisoformat(body.post_date)
        except ValueError:
            return JSONResponse({"error": "Invalid date format. Use ISO format."}, status_code=400)

    post = CompetitorPost(
        competitor_id=competitor_id,
        content=body.content,
        post_url=body.post_url or None,
        post_date=post_date,
        likes=body.likes,
        comments=body.comments,
        shares=body.shares,
        hook_style=body.hook_style or None,
        content_format=body.content_format or None,
        topic=body.topic or None,
        key_takeaway=body.key_takeaway or None,
        why_it_works=body.why_it_works or None,
    )
    db.add(post)

    # Update competitor aggregate stats
    all_posts = comp.posts + [post]
    comp.total_posts_tracked = len(all_posts)
    comp.avg_likes = round(sum(p.likes for p in all_posts) / len(all_posts), 2)
    comp.avg_comments = round(sum(p.comments for p in all_posts) / len(all_posts), 2)

    db.commit()
    db.refresh(post)
    return {
        "status": "created",
        "id": post.id,
        "competitor_id": competitor_id,
    }


@router.delete("/api/competitors/posts/{post_id}")
async def api_delete_competitor_post(post_id: int, db: Session = Depends(get_db)):
    """Delete a specific competitor post and recalculate competitor stats."""
    post = db.query(CompetitorPost).get(post_id)
    if not post:
        return JSONResponse({"error": "Post not found"}, status_code=404)

    comp = post.competitor
    db.delete(post)
    db.flush()

    # Recalculate competitor stats after deletion
    remaining = db.query(CompetitorPost).filter(CompetitorPost.competitor_id == comp.id).all()
    comp.total_posts_tracked = len(remaining)
    if remaining:
        comp.avg_likes = round(sum(p.likes for p in remaining) / len(remaining), 2)
        comp.avg_comments = round(sum(p.comments for p in remaining) / len(remaining), 2)
    else:
        comp.avg_likes = 0.0
        comp.avg_comments = 0.0

    db.commit()
    return {"status": "deleted", "id": post_id}


@router.post("/api/competitors/posts/{post_id}/save")
async def api_toggle_save_post(post_id: int, db: Session = Depends(get_db)):
    """Toggle the is_saved flag on a competitor post."""
    post = db.query(CompetitorPost).get(post_id)
    if not post:
        return JSONResponse({"error": "Post not found"}, status_code=404)
    post.is_saved = not post.is_saved
    db.commit()
    return {"status": "toggled", "id": post.id, "is_saved": post.is_saved}


@router.get("/api/competitors/{competitor_id}/detail")
async def api_competitor_detail(competitor_id: int, db: Session = Depends(get_db)):
    """Full detail view for a single competitor: profile, posts, engagement analytics, content patterns."""
    comp = db.query(Competitor).get(competitor_id)
    if not comp:
        return JSONResponse({"error": "Competitor not found"}, status_code=404)

    posts = (
        db.query(CompetitorPost)
        .filter(CompetitorPost.competitor_id == competitor_id)
        .order_by(CompetitorPost.post_date.desc().nullslast(), CompetitorPost.created_at.desc())
        .all()
    )

    # --- Engagement stats ---
    total_likes = sum(p.likes for p in posts)
    total_comments = sum(p.comments for p in posts)
    total_shares = sum(p.shares for p in posts)
    total_posts = len(posts)
    avg_likes = round(total_likes / total_posts, 1) if total_posts else 0
    avg_comments = round(total_comments / total_posts, 1) if total_posts else 0
    avg_shares = round(total_shares / total_posts, 1) if total_posts else 0
    avg_engagement = round((total_likes + total_comments + total_shares) / total_posts, 1) if total_posts else 0

    # --- Top 5 posts by total engagement ---
    top_posts = sorted(posts, key=lambda p: p.likes + p.comments + p.shares, reverse=True)[:5]

    # --- Content pattern analysis ---
    hook_counts: dict[str, int] = {}
    format_counts: dict[str, int] = {}
    topic_counts: dict[str, int] = {}
    for p in posts:
        if p.hook_style:
            hook_counts[p.hook_style] = hook_counts.get(p.hook_style, 0) + 1
        if p.content_format:
            format_counts[p.content_format] = format_counts.get(p.content_format, 0) + 1
        if p.topic:
            topic_counts[p.topic] = topic_counts.get(p.topic, 0) + 1

    # --- Engagement by hook style ---
    hook_engagement: dict[str, dict] = {}
    for p in posts:
        if p.hook_style:
            if p.hook_style not in hook_engagement:
                hook_engagement[p.hook_style] = {"total_eng": 0, "count": 0}
            hook_engagement[p.hook_style]["total_eng"] += p.likes + p.comments + p.shares
            hook_engagement[p.hook_style]["count"] += 1
    hook_perf = [
        {"style": k, "avg_engagement": round(v["total_eng"] / v["count"], 1), "count": v["count"]}
        for k, v in hook_engagement.items()
    ]
    hook_perf.sort(key=lambda x: x["avg_engagement"], reverse=True)

    # --- Engagement by format ---
    format_engagement: dict[str, dict] = {}
    for p in posts:
        if p.content_format:
            if p.content_format not in format_engagement:
                format_engagement[p.content_format] = {"total_eng": 0, "count": 0}
            format_engagement[p.content_format]["total_eng"] += p.likes + p.comments + p.shares
            format_engagement[p.content_format]["count"] += 1
    format_perf = [
        {"format": k, "avg_engagement": round(v["total_eng"] / v["count"], 1), "count": v["count"]}
        for k, v in format_engagement.items()
    ]
    format_perf.sort(key=lambda x: x["avg_engagement"], reverse=True)

    # --- Posting timeline (engagement over time) ---
    timeline = []
    for p in sorted(posts, key=lambda x: x.post_date or x.created_at):
        timeline.append({
            "date": (p.post_date or p.created_at).isoformat() if (p.post_date or p.created_at) else None,
            "likes": p.likes,
            "comments": p.comments,
            "shares": p.shares,
            "total": p.likes + p.comments + p.shares,
        })

    # --- Media stats ---
    posts_with_image = sum(1 for p in posts if p.has_image)
    posts_with_video = sum(1 for p in posts if p.has_video)
    posts_text_only = total_posts - posts_with_image - posts_with_video

    # --- AI analysis coverage ---
    analyzed_count = sum(1 for p in posts if p.ai_analyzed)
    saved_count = sum(1 for p in posts if p.is_saved)

    # --- All key takeaways ---
    takeaways = [
        {"post_id": p.id, "takeaway": p.key_takeaway, "topic": p.topic, "likes": p.likes}
        for p in posts if p.key_takeaway
    ]

    # Serialize posts
    posts_data = [
        {
            "id": p.id,
            "content": p.content,
            "post_url": p.post_url,
            "post_date": p.post_date.isoformat() if p.post_date else None,
            "likes": p.likes,
            "comments": p.comments,
            "shares": p.shares,
            "total_engagement": p.likes + p.comments + p.shares,
            "has_image": p.has_image,
            "has_video": p.has_video,
            "image_url": p.image_url,
            "hook_style": p.hook_style,
            "content_format": p.content_format,
            "topic": p.topic,
            "key_takeaway": p.key_takeaway,
            "why_it_works": p.why_it_works,
            "how_to_recreate": p.how_to_recreate,
            "ai_analyzed": p.ai_analyzed,
            "is_saved": p.is_saved,
            "recreated": p.recreated,
            "source": p.source,
        }
        for p in posts
    ]

    return {
        "profile": {
            "id": comp.id,
            "name": comp.name,
            "linkedin_url": comp.linkedin_url,
            "linkedin_username": comp.linkedin_username,
            "niche": comp.niche,
            "notes": comp.notes,
            "profile_picture": comp.profile_picture,
            "headline": comp.headline,
            "follower_count": comp.follower_count or 0,
            "posting_frequency": comp.posting_frequency,
            "last_scraped_at": comp.last_scraped_at.isoformat() if comp.last_scraped_at else None,
            "scrape_status": comp.scrape_status,
            "created_at": comp.created_at.isoformat() if comp.created_at else None,
        },
        "stats": {
            "total_posts": total_posts,
            "total_likes": total_likes,
            "total_comments": total_comments,
            "total_shares": total_shares,
            "avg_likes": avg_likes,
            "avg_comments": avg_comments,
            "avg_shares": avg_shares,
            "avg_engagement": avg_engagement,
            "posts_with_image": posts_with_image,
            "posts_with_video": posts_with_video,
            "posts_text_only": posts_text_only,
            "analyzed_count": analyzed_count,
            "saved_count": saved_count,
        },
        "top_posts": [
            {
                "id": p.id,
                "content": p.content[:200] + "..." if len(p.content) > 200 else p.content,
                "likes": p.likes,
                "comments": p.comments,
                "shares": p.shares,
                "total_engagement": p.likes + p.comments + p.shares,
                "hook_style": p.hook_style,
                "content_format": p.content_format,
                "topic": p.topic,
                "post_url": p.post_url,
                "post_date": p.post_date.isoformat() if p.post_date else None,
            }
            for p in top_posts
        ],
        "patterns": {
            "hook_styles": sorted(hook_counts.items(), key=lambda x: x[1], reverse=True),
            "formats": sorted(format_counts.items(), key=lambda x: x[1], reverse=True),
            "topics": sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:10],
            "hook_performance": hook_perf,
            "format_performance": format_perf,
        },
        "takeaways": takeaways,
        "timeline": timeline,
        "posts": posts_data,
    }


@router.get("/api/competitors/insights")
async def api_competitors_insights(db: Session = Depends(get_db)):
    """Return aggregate insights across all competitors."""
    total_competitors = db.query(func.count(Competitor.id)).scalar() or 0
    total_posts_tracked = db.query(func.count(CompetitorPost.id)).scalar() or 0

    # Top performing post (most likes) — single query with join
    top_performing_post = None
    best = (
        db.query(CompetitorPost, Competitor.name)
        .join(Competitor, CompetitorPost.competitor_id == Competitor.id)
        .order_by(CompetitorPost.likes.desc())
        .first()
    )
    if best:
        bp, comp_name = best
        top_performing_post = {
            "id": bp.id,
            "competitor_id": bp.competitor_id,
            "competitor_name": comp_name,
            "content": bp.content[:200] + "..." if len(bp.content) > 200 else bp.content,
            "likes": bp.likes,
            "comments": bp.comments,
            "shares": bp.shares,
            "hook_style": bp.hook_style,
            "content_format": bp.content_format,
            "topic": bp.topic,
        }

    # Most common hook style — SQL GROUP BY
    most_common_hook_style = None
    hook_row = (
        db.query(CompetitorPost.hook_style, func.count(CompetitorPost.id).label("cnt"))
        .filter(CompetitorPost.hook_style.isnot(None), CompetitorPost.hook_style != "")
        .group_by(CompetitorPost.hook_style)
        .order_by(func.count(CompetitorPost.id).desc())
        .first()
    )
    if hook_row:
        most_common_hook_style = hook_row[0]

    # Most common content format — SQL GROUP BY
    most_common_format = None
    fmt_row = (
        db.query(CompetitorPost.content_format, func.count(CompetitorPost.id).label("cnt"))
        .filter(CompetitorPost.content_format.isnot(None), CompetitorPost.content_format != "")
        .group_by(CompetitorPost.content_format)
        .order_by(func.count(CompetitorPost.id).desc())
        .first()
    )
    if fmt_row:
        most_common_format = fmt_row[0]

    # Average engagement by competitor — single aggregation query
    agg = (
        db.query(
            Competitor.id,
            Competitor.name,
            func.count(CompetitorPost.id).label("posts_count"),
            func.avg(CompetitorPost.likes).label("avg_likes"),
            func.avg(CompetitorPost.comments).label("avg_comments"),
            func.avg(CompetitorPost.shares).label("avg_shares"),
        )
        .outerjoin(CompetitorPost, Competitor.id == CompetitorPost.competitor_id)
        .group_by(Competitor.id, Competitor.name)
        .all()
    )
    avg_engagement_by_competitor = []
    for row in agg:
        al = round(row.avg_likes or 0, 2)
        ac = round(row.avg_comments or 0, 2)
        ash = round(row.avg_shares or 0, 2)
        avg_engagement_by_competitor.append({
            "competitor_id": row.id,
            "competitor_name": row.name,
            "posts_count": row.posts_count,
            "avg_likes": al,
            "avg_comments": ac,
            "avg_shares": ash,
            "avg_total_engagement": round(al + ac + ash, 2),
        })
    avg_engagement_by_competitor.sort(key=lambda x: x["avg_total_engagement"], reverse=True)

    return {
        "total_competitors": total_competitors,
        "total_posts_tracked": total_posts_tracked,
        "top_performing_post": top_performing_post,
        "most_common_hook_style": most_common_hook_style,
        "most_common_format": most_common_format,
        "avg_engagement_by_competitor": avg_engagement_by_competitor,
    }


# ── Competitor Scraper API routes ─────────────────────────────


@router.post("/api/competitors/scrape-all")
async def api_scrape_all_competitors(db: Session = Depends(get_db)):
    """Trigger a full scrape of all competitors (profile + posts + AI analysis)."""
    from research.competitor_scraper import CompetitorScraper

    scraper = CompetitorScraper(db)
    results = scraper.scrape_all_competitors()
    return results


@router.post("/api/competitors/{competitor_id}/scrape")
async def api_scrape_competitor(competitor_id: int, db: Session = Depends(get_db)):
    """Scrape a single competitor's profile and posts."""
    comp = db.query(Competitor).get(competitor_id)
    if not comp:
        return JSONResponse({"error": "Competitor not found"}, status_code=404)

    from research.competitor_scraper import CompetitorScraper

    scraper = CompetitorScraper(db)
    try:
        new_posts = scraper.scrape_competitor(comp)
        analyzed = scraper._analyze_unanalyzed_posts(comp)
        return {
            "status": "success",
            "competitor": comp.name,
            "new_posts": new_posts,
            "analyzed": analyzed,
            "total_posts": comp.total_posts_tracked,
            "follower_count": comp.follower_count,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/competitors/posts/{post_id}/analyze")
async def api_analyze_post(post_id: int, db: Session = Depends(get_db)):
    """Run AI analysis on a single competitor post."""
    from research.competitor_scraper import CompetitorScraper

    scraper = CompetitorScraper(db)
    success = scraper.analyze_single_post(post_id)
    if not success:
        return JSONResponse({"error": "Post not found or analysis failed"}, status_code=404)

    post = db.query(CompetitorPost).get(post_id)
    return {
        "status": "analyzed",
        "hook_style": post.hook_style,
        "content_format": post.content_format,
        "topic": post.topic,
        "key_takeaway": post.key_takeaway,
        "why_it_works": post.why_it_works,
        "how_to_recreate": post.how_to_recreate,
    }


@router.post("/api/competitors/posts/{post_id}/recreate")
async def api_recreate_from_competitor(post_id: int, db: Session = Depends(get_db)):
    """Generate an AI-written original post inspired by a competitor's viral post."""
    source = db.query(CompetitorPost).get(post_id)
    if not source:
        return JSONResponse({"error": "Source post not found"}, status_code=404)

    competitor_name = source.competitor.name if source.competitor else "Unknown"
    engagement_stats = f"{source.likes} likes, {source.comments} comments, {source.shares} shares"

    gen = ContentGenerator(db)
    post = gen.generate_from_competitor(
        competitor_name=competitor_name,
        competitor_content=source.content or "",
        hook_style=source.hook_style or "",
        content_format=source.content_format or "",
        topic=source.topic or "",
        why_it_works=source.why_it_works or "",
        how_to_recreate=source.how_to_recreate or "",
        engagement_stats=engagement_stats,
    )

    if not post:
        return JSONResponse({"error": "AI generation failed — please try again"}, status_code=500)

    source.recreated = True
    db.commit()

    return {
        "status": "recreated",
        "new_post_id": post.id,
        "content": post.content,
        "word_count": post.word_count,
        "virality_score": post.virality_score,
    }


# ── My Profile Scraper API routes ─────────────────────────────


class ProfileUrlUpdate(BaseModel):
    linkedin_profile_url: str


@router.post("/api/profile/set-url")
async def api_set_profile_url(body: ProfileUrlUpdate):
    """Save the user's LinkedIn profile URL to .env file."""
    import re

    url = body.linkedin_profile_url.strip()
    if not url:
        return JSONResponse({"error": "URL cannot be empty"}, status_code=400)

    # Validate it looks like a LinkedIn URL or username
    if not re.search(r"linkedin\.com/in/|^[a-zA-Z0-9_-]+$", url):
        return JSONResponse({"error": "Invalid LinkedIn profile URL"}, status_code=400)

    # Sanitize: strip newlines and control characters to prevent .env injection
    url = re.sub(r"[\r\n\x00-\x1f]", "", url).strip()
    if not url:
        return JSONResponse({"error": "Invalid URL after sanitization"}, status_code=400)

    # Update .env file
    env_path = ".env"
    try:
        with open(env_path, "r") as f:
            lines = f.readlines()

        found = False
        for i, line in enumerate(lines):
            if line.startswith("LINKEDIN_PROFILE_URL="):
                lines[i] = f"LINKEDIN_PROFILE_URL={url}\n"
                found = True
                break

        if not found:
            lines.append(f"\n# My LinkedIn Profile\nLINKEDIN_PROFILE_URL={url}\n")

        with open(env_path, "w") as f:
            f.writelines(lines)

        # Update runtime setting
        settings.LINKEDIN_PROFILE_URL = url

    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Failed to save profile URL: %s", e)
        return JSONResponse({"error": "Failed to save profile URL"}, status_code=500)

    return {"status": "saved", "url": url}


@router.get("/api/profile/url")
async def api_get_profile_url():
    """Get the currently configured LinkedIn profile URL."""
    return {"url": settings.LINKEDIN_PROFILE_URL}


@router.post("/api/profile/scrape")
async def api_scrape_my_profile(db: Session = Depends(get_db)):
    """Trigger a scrape of the user's own LinkedIn profile and posts via Apify."""
    from research.profile_scraper import ProfileScraper

    scraper = ProfileScraper(db)
    result = scraper.scrape_my_profile()

    if "error" in result:
        return JSONResponse({"error": result["error"]}, status_code=400)

    return result


@router.get("/api/profile/stats")
async def api_profile_stats(db: Session = Depends(get_db)):
    """Get aggregate stats for the user's scraped LinkedIn posts."""
    from research.profile_scraper import ProfileScraper

    scraper = ProfileScraper(db)
    return scraper.get_profile_stats()


@router.get("/api/profile/posts")
async def api_profile_posts(
    sort: str = "engagement",
    limit: int = 10,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Get the user's scraped LinkedIn posts sorted by date or engagement."""
    from database.models import MyLinkedInPost

    base_query = db.query(MyLinkedInPost)
    total = base_query.count()

    if sort == "date":
        base_query = base_query.order_by(MyLinkedInPost.post_date.desc())
    else:
        # Sort by weighted engagement score in SQL
        eng_expr = MyLinkedInPost.likes + MyLinkedInPost.comments * 3 + MyLinkedInPost.shares * 5
        base_query = base_query.order_by(eng_expr.desc())

    posts = base_query.offset(offset).limit(limit).all()

    result = []
    for p in posts:
        eng_score = p.likes + p.comments * 3 + p.shares * 5
        result.append({
            "id": p.id,
            "content": p.content,
            "post_url": p.post_url,
            "linkedin_post_id": p.linkedin_post_id,
            "post_date": p.post_date.isoformat() if p.post_date else None,
            "likes": p.likes,
            "comments": p.comments,
            "shares": p.shares,
            "engagement_score": eng_score,
            "has_image": p.has_image,
            "has_video": p.has_video,
            "image_url": p.image_url,
            "hook_style": p.hook_style,
            "content_format": p.content_format,
            "topic": p.topic,
            "key_takeaway": p.key_takeaway,
            "why_it_works": p.why_it_works,
            "ai_analyzed": p.ai_analyzed,
        })

    return {"items": result, "total": total, "limit": limit, "offset": offset}


@router.get("/api/profile/timeline")
async def api_profile_timeline(db: Session = Depends(get_db)):
    """Get chronological posting data for timeline chart."""
    from collections import defaultdict
    from database.models import MyLinkedInPost

    posts = (
        db.query(MyLinkedInPost)
        .filter(MyLinkedInPost.post_date.isnot(None))
        .order_by(MyLinkedInPost.post_date.asc())
        .all()
    )

    # Group by week
    weeks: dict[str, dict] = defaultdict(
        lambda: {"posts": 0, "likes": 0, "comments": 0, "shares": 0}
    )
    for p in posts:
        from datetime import timedelta
        week_start = p.post_date.date() - timedelta(days=p.post_date.weekday())
        key = week_start.isoformat()
        weeks[key]["posts"] += 1
        weeks[key]["likes"] += p.likes
        weeks[key]["comments"] += p.comments
        weeks[key]["shares"] += p.shares

    timeline = []
    for week, data in sorted(weeks.items()):
        timeline.append({"week": week, **data})

    return timeline


# ── Research Dashboard API routes ─────────────────────────────


@router.get("/api/research/items")
async def api_get_research_items(
    source: str | None = None,
    region: str | None = None,
    category: str | None = None,
    saved_only: bool = False,
    unused_only: bool = False,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Get research items with optional filters."""
    query = db.query(ResearchItem)

    if source:
        query = query.filter(ResearchItem.source == source)
    if region:
        query = query.filter(ResearchItem.region == region)
    if category:
        query = query.filter(ResearchItem.category == category)
    if saved_only:
        query = query.filter(ResearchItem.saved.is_(True))
    if unused_only:
        query = query.filter(ResearchItem.used.is_(False))

    items = (
        query.order_by(ResearchItem.fetched_at.desc())
        .limit(limit)
        .all()
    )

    # Build performance score map for items that generated posts
    item_ids = [item.id for item in items]
    perf_map = {}
    if item_ids:
        perf_rows = (
            db.query(
                QueuedPost.research_item_id,
                func.max(
                    PostPerformance.likes + PostPerformance.comments * 3 + PostPerformance.shares * 5
                ).label("best_engagement"),
            )
            .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
            .filter(QueuedPost.research_item_id.in_(item_ids))
            .group_by(QueuedPost.research_item_id)
            .all()
        )
        perf_map = {r[0]: r[1] for r in perf_rows}

    return [
        {
            "id": item.id,
            "source": item.source,
            "topic": item.topic,
            "title": item.title,
            "content": item.content,
            "url": item.url,
            "relevance_score": item.relevance_score,
            "used": item.used,
            "saved": item.saved,
            "region": item.region,
            "category": item.category,
            "notes": item.notes,
            "normalized_topic_key": item.normalized_topic_key,
            "appearance_count": item.appearance_count,
            "velocity": item.velocity,
            "first_seen_at": (item.first_seen_at.isoformat() + "Z") if item.first_seen_at else None,
            "fetched_at": (item.fetched_at.isoformat() + "Z") if item.fetched_at else None,
            "performance_score": perf_map.get(item.id),
        }
        for item in items
    ]


@router.get("/api/research/sources")
async def api_get_research_sources(db: Session = Depends(get_db)):
    """Get distinct research sources and their counts."""
    rows = (
        db.query(
            func.coalesce(ResearchItem.source, "unknown").label("source"),
            func.count(ResearchItem.id).label("cnt"),
        )
        .group_by(func.coalesce(ResearchItem.source, "unknown"))
        .order_by(func.count(ResearchItem.id).desc())
        .all()
    )
    return [{"source": r.source, "count": r.cnt} for r in rows]


@router.get("/api/research/regions")
async def api_get_research_regions(db: Session = Depends(get_db)):
    """Get distinct regions and their counts."""
    rows = (
        db.query(
            func.coalesce(ResearchItem.region, "global").label("region"),
            func.count(ResearchItem.id).label("cnt"),
        )
        .group_by(func.coalesce(ResearchItem.region, "global"))
        .order_by(func.count(ResearchItem.id).desc())
        .all()
    )
    return [{"region": r.region, "count": r.cnt} for r in rows]


@router.get("/api/research/categories")
async def api_get_research_categories(db: Session = Depends(get_db)):
    """Get distinct categories and their counts."""
    rows = (
        db.query(
            func.coalesce(ResearchItem.category, "unknown").label("category"),
            func.count(ResearchItem.id).label("cnt"),
        )
        .group_by(func.coalesce(ResearchItem.category, "unknown"))
        .order_by(func.count(ResearchItem.id).desc())
        .all()
    )
    return [{"category": r.category, "count": r.cnt} for r in rows]


@router.get("/api/research/stats")
async def api_get_research_stats(db: Session = Depends(get_db)):
    """Get research overview stats."""
    # Single query for counts and avg relevance
    stats_row = db.query(
        func.count(ResearchItem.id).label("total"),
        func.sum(func.cast(ResearchItem.saved == True, Integer)).label("saved"),
        func.sum(func.cast(ResearchItem.used == True, Integer)).label("used"),
        func.sum(func.cast(ResearchItem.used == False, Integer)).label("unused"),
        func.avg(ResearchItem.relevance_score).label("avg_rel"),
        func.max(ResearchItem.fetched_at).label("last_run"),
    ).first()

    total = stats_row.total or 0
    last_run = (stats_row.last_run.isoformat() + "Z") if stats_row.last_run else None
    avg_relevance = round(stats_row.avg_rel or 0, 2)

    # Source breakdown — SQL GROUP BY
    source_rows = (
        db.query(
            func.coalesce(ResearchItem.source, "unknown"),
            func.count(ResearchItem.id),
        )
        .group_by(func.coalesce(ResearchItem.source, "unknown"))
        .all()
    )
    sources = {r[0]: r[1] for r in source_rows}

    # Region breakdown — SQL GROUP BY
    region_rows = (
        db.query(
            func.coalesce(ResearchItem.region, "global"),
            func.count(ResearchItem.id),
        )
        .group_by(func.coalesce(ResearchItem.region, "global"))
        .all()
    )
    regions = {r[0]: r[1] for r in region_rows}

    # Category breakdown — SQL GROUP BY
    cat_rows = (
        db.query(
            func.coalesce(ResearchItem.category, "unknown"),
            func.count(ResearchItem.id),
        )
        .group_by(func.coalesce(ResearchItem.category, "unknown"))
        .all()
    )
    categories = {r[0]: r[1] for r in cat_rows}

    return {
        "total_items": total,
        "saved_items": stats_row.saved or 0,
        "used_items": stats_row.used or 0,
        "unused_items": stats_row.unused or 0,
        "last_run": last_run,
        "avg_relevance": avg_relevance,
        "sources": sources,
        "regions": regions,
        "categories": categories,
    }


@router.get("/api/research/topic-map")
async def api_research_topic_map(db: Session = Depends(get_db)):
    """Build a topic map: nodes (topics) and edges (shared categories/sources)."""
    items = (
        db.query(ResearchItem)
        .filter(ResearchItem.topic.isnot(None), ResearchItem.topic != "")
        .order_by(ResearchItem.relevance_score.desc())
        .limit(200)
        .all()
    )

    # Build nodes grouped by normalized_topic_key or category
    from collections import defaultdict
    cat_topics = defaultdict(list)
    nodes = []
    seen = set()

    for item in items:
        key = item.normalized_topic_key or item.topic[:60]
        if key in seen:
            # Bump count for existing node
            for n in nodes:
                if n["id"] == key:
                    n["count"] += 1
                    n["relevance"] = max(n["relevance"], item.relevance_score or 0)
                    break
            continue
        seen.add(key)
        nodes.append({
            "id": key,
            "label": (item.topic or key)[:50],
            "category": item.category or "general",
            "source": item.source or "unknown",
            "relevance": round(item.relevance_score or 0, 1),
            "velocity": item.velocity or "stable",
            "used": item.used or False,
            "saved": item.saved or False,
            "count": 1,
        })
        if item.category:
            cat_topics[item.category].append(key)

    # Build edges: topics in the same category are connected
    edges = []
    edge_set = set()
    for cat, topic_keys in cat_topics.items():
        for i in range(len(topic_keys)):
            for j in range(i + 1, min(i + 4, len(topic_keys))):
                pair = tuple(sorted([topic_keys[i], topic_keys[j]]))
                if pair not in edge_set:
                    edge_set.add(pair)
                    edges.append({"source": pair[0], "target": pair[1], "category": cat})

    return {"nodes": nodes[:80], "edges": edges[:200]}


@router.post("/api/research/items/{item_id}/save")
async def api_toggle_save_research(item_id: int, db: Session = Depends(get_db)):
    """Toggle the saved/bookmarked status of a research item."""
    item = db.query(ResearchItem).get(item_id)
    if not item:
        return JSONResponse({"error": "Research item not found"}, status_code=404)
    item.saved = not item.saved
    db.commit()
    return {"status": "toggled", "id": item.id, "saved": item.saved}


@router.post("/api/research/items/{item_id}/use")
async def api_mark_used(item_id: int, db: Session = Depends(get_db)):
    """Mark a research item as used (already generated content from it)."""
    item = db.query(ResearchItem).get(item_id)
    if not item:
        return JSONResponse({"error": "Research item not found"}, status_code=404)
    item.used = not item.used
    db.commit()
    return {"status": "toggled", "id": item.id, "used": item.used}


@router.delete("/api/research/items/{item_id}")
async def api_delete_research_item(item_id: int, db: Session = Depends(get_db)):
    """Delete a specific research item."""
    item = db.query(ResearchItem).get(item_id)
    if not item:
        return JSONResponse({"error": "Research item not found"}, status_code=404)
    db.delete(item)
    db.commit()
    return {"status": "deleted", "id": item_id}


@router.post("/api/research/clear-old")
async def api_clear_old_research(days: int = 30, db: Session = Depends(get_db)):
    """Delete research items older than specified days (keeps saved ones)."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = (
        db.query(ResearchItem)
        .filter(
            ResearchItem.fetched_at < cutoff,
            ResearchItem.saved.is_(False),
        )
        .delete()
    )
    db.commit()
    return {"status": "cleared", "deleted": deleted}


# ── Research batch operations ──


@router.post("/api/research/batch/save")
async def api_batch_save_research(body: ResearchBulkActionRequest, db: Session = Depends(get_db)):
    """Batch save/bookmark multiple research items."""
    items = db.query(ResearchItem).filter(ResearchItem.id.in_(body.item_ids)).all()
    for item in items:
        item.saved = True
    db.commit()
    return {"status": "saved", "count": len(items)}


@router.post("/api/research/batch/mark-used")
async def api_batch_mark_used(body: ResearchBulkActionRequest, db: Session = Depends(get_db)):
    """Batch mark multiple research items as used."""
    items = db.query(ResearchItem).filter(ResearchItem.id.in_(body.item_ids)).all()
    for item in items:
        item.used = True
    db.commit()
    return {"status": "marked_used", "count": len(items)}


@router.post("/api/research/batch/delete")
async def api_batch_delete_research(body: ResearchBulkActionRequest, db: Session = Depends(get_db)):
    """Batch delete multiple research items."""
    deleted = (
        db.query(ResearchItem)
        .filter(ResearchItem.id.in_(body.item_ids))
        .delete(synchronize_session="fetch")
    )
    db.commit()
    return {"status": "deleted", "count": deleted}


@router.post("/api/research/batch/create-posts")
async def api_batch_create_posts(body: ResearchBulkActionRequest, db: Session = Depends(get_db)):
    """Batch create LinkedIn posts from multiple research items."""
    results = []
    for item_id in body.item_ids:
        item = db.query(ResearchItem).get(item_id)
        if not item:
            continue
        research_context = (
            f"RESEARCH SOURCE: {item.source}\n"
            f"TOPIC: {item.topic}\n"
            f"TITLE: {item.title}\n"
            f"CONTENT: {item.content}\n"
        )
        if item.url:
            research_context += f"URL: {item.url}\n"
        gen = ContentGenerator(db)
        post = gen.generate_single(
            topic=item.topic or item.title or "e-commerce insights",
            tone="authoritative",
        )
        if post:
            post.research_context = research_context
            post.research_item_id = item.id
            item.used = True
            db.commit()
            results.append({"item_id": item_id, "post_id": post.id})
    return {"status": "created", "posts": results, "count": len(results)}


# ── Manual research items + notes ──


@router.post("/api/research/items")
async def api_create_manual_research(body: ManualResearchItemCreate, db: Session = Depends(get_db)):
    """Create a manual research item."""
    item = ResearchItem(
        source="manual",
        topic=body.topic,
        title=body.title or body.topic,
        content=body.content,
        url=body.url or None,
        category=body.category or None,
        region=body.region or None,
        relevance_score=body.relevance_score,
        used=False,
        saved=False,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"status": "created", "id": item.id, "topic": item.topic}


@router.put("/api/research/items/{item_id}/notes")
async def api_update_research_notes(item_id: int, body: UpdateNotesRequest, db: Session = Depends(get_db)):
    """Update notes/annotations on a research item."""
    item = db.query(ResearchItem).get(item_id)
    if not item:
        return JSONResponse({"error": "Research item not found"}, status_code=404)
    item.notes = body.notes
    db.commit()
    return {"status": "updated", "id": item.id, "notes": item.notes}


# ── Research performance tracking ──


@router.get("/api/research/performance")
async def api_research_performance_stats(db: Session = Depends(get_db)):
    """Compare engagement of research-based posts vs. non-research posts."""
    # Research-based posts (have research_item_id)
    research_posts = (
        db.query(QueuedPost, PostPerformance)
        .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
        .filter(
            QueuedPost.status == PostStatus.POSTED,
            QueuedPost.research_item_id.isnot(None),
        )
        .all()
    )

    # Non-research posts
    non_research_posts = (
        db.query(QueuedPost, PostPerformance)
        .join(PostPerformance, QueuedPost.id == PostPerformance.post_id)
        .filter(
            QueuedPost.status == PostStatus.POSTED,
            QueuedPost.research_item_id.is_(None),
        )
        .all()
    )

    def avg_engagement(rows):
        if not rows:
            return 0
        scores = [(p.likes or 0) + (p.comments or 0) * 3 + (p.shares or 0) * 5 for _, p in rows]
        return round(sum(scores) / len(scores), 1)

    research_avg = avg_engagement(research_posts)
    non_research_avg = avg_engagement(non_research_posts)
    lift_pct = round(((research_avg / non_research_avg) - 1) * 100, 1) if non_research_avg > 0 else 0

    # Top performing research items
    top_items = []
    for post, perf in sorted(
        research_posts,
        key=lambda x: (x[1].likes or 0) + (x[1].comments or 0) * 3 + (x[1].shares or 0) * 5,
        reverse=True,
    )[:5]:
        if post.research_item_id:
            item = db.query(ResearchItem).get(post.research_item_id)
            if item:
                top_items.append({
                    "item_id": item.id,
                    "topic": item.topic,
                    "source": item.source,
                    "post_id": post.id,
                    "engagement": (perf.likes or 0) + (perf.comments or 0) * 3 + (perf.shares or 0) * 5,
                })

    return {
        "research_based_count": len(research_posts),
        "non_research_count": len(non_research_posts),
        "research_avg_engagement": research_avg,
        "non_research_avg_engagement": non_research_avg,
        "lift_pct": lift_pct,
        "top_performing_items": top_items,
    }


@router.post("/api/research/items/{item_id}/create-post")
async def api_create_post_from_research(item_id: int, db: Session = Depends(get_db)):
    """Generate a LinkedIn news summary post from a research item.

    Uses the news summary prompt — bullet-point format, no personal angle.
    Just curates and shares the news for the audience.
    """
    item = db.query(ResearchItem).get(item_id)
    if not item:
        return JSONResponse({"error": "Research item not found"}, status_code=404)

    import json as json_mod
    from config import get_anthropic_client
    from content.prompt_builder import build_news_summary_prompt
    from content.post_formatter import format_for_linkedin
    from content.virality_scorer import ViralityScorer

    prompt = build_news_summary_prompt(
        topic=item.topic or "e-commerce insights",
        title=item.title or "",
        content=item.content or "",
        source=item.source or "",
        url=item.url or "",
    )

    try:
        client = get_anthropic_client()
        message = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=settings.CLAUDE_MAX_TOKENS,
            temperature=settings.CLAUDE_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
        )
        content = message.content[0].text.strip()
    except Exception as e:
        return JSONResponse({"error": f"Generation failed: {e}"}, status_code=500)

    content = format_for_linkedin(content, item.topic or "")

    # Score virality
    scorer = ViralityScorer()
    score_result = scorer.score(content, item.topic or "")

    # Build research context for reference
    research_context = (
        f"RESEARCH SOURCE: {item.source}\n"
        f"TOPIC: {item.topic}\n"
        f"TITLE: {item.title}\n"
        f"CONTENT: {item.content}\n"
    )
    if item.url:
        research_context += f"URL: {item.url}\n"

    post = QueuedPost(
        content=content,
        topic=item.topic or item.title,
        status=PostStatus.QUEUED,
        research_context=research_context,
        research_item_id=item.id,
        virality_score=score_result.get("total_score"),
        virality_breakdown=json_mod.dumps(score_result),
        virality_performance=score_result.get("predicted_performance"),
        word_count=len(content.split()),
    )
    db.add(post)
    db.commit()

    # Mark research item as used
    item.used = True
    db.commit()

    return {
        "status": "created",
        "post_id": post.id,
        "content": post.content,
        "virality_score": post.virality_score,
        "virality_performance": post.virality_performance,
        "virality_breakdown": post.virality_breakdown,
    }


@router.post("/api/queue/{post_id}/score-virality")
async def api_score_virality(post_id: int, db: Session = Depends(get_db)):
    """Score or re-score a post's virality."""
    import json as json_mod
    from content.virality_scorer import ViralityScorer

    post = db.query(QueuedPost).filter(QueuedPost.id == post_id).first()
    if not post:
        return JSONResponse({"error": "Post not found"}, status_code=404)

    scorer = ViralityScorer()
    result = scorer.score(post.content, post.topic or "")

    post.virality_score = result.get("total_score")
    post.virality_breakdown = json_mod.dumps(result)
    post.virality_performance = result.get("predicted_performance")
    db.commit()

    return {
        "status": "scored",
        "id": post_id,
        "virality_score": post.virality_score,
        "virality_performance": post.virality_performance,
        "virality_breakdown": post.virality_breakdown,
    }


# ── Idea Lab API routes ──────────────────────────────────────


@router.post("/api/idea/generate")
async def api_generate_from_idea(body: IdeaRequest, db: Session = Depends(get_db)):
    """Generate multiple post variations from a freeform idea."""
    if not body.idea.strip():
        return JSONResponse({"error": "Please enter your post idea"}, status_code=400)

    gen = ContentGenerator(db)
    posts = []

    for variant in body.variants:
        try:
            post = gen.generate_from_idea(
                idea=body.idea.strip(),
                variant=variant,
                formats=body.formats,
                tones=body.tones,
                angles=body.angles,
                structures=body.structures,
            )
            if post:
                posts.append({
                    "post_id": post.id,
                    "content": post.content,
                    "variant": variant,
                    "word_count": post.word_count,
                    "virality_score": post.virality_score,
                    "virality_performance": post.virality_performance,
                    "virality_breakdown": post.virality_breakdown,
                    "fact_check_status": post.fact_check_status,
                })
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("Idea generation failed for variant '%s': %s", variant, e)
            continue

    return {"status": "generated", "posts": posts}


@router.post("/api/idea/suggest-topic")
async def api_suggest_topic(db: Session = Depends(get_db)):
    """Suggest a trending topic for post creation using Claude."""
    from config import get_anthropic_client
    import random as _random

    client = get_anthropic_client()

    # Rotate through content pillars so we don't always get the same category
    categories = [
        "AI tools replacing or augmenting agency/marketing work (with specific tool names and results)",
        "Client case study with real dollar amounts (CRO, Klaviyo, Meta Ads, or Shopify optimization)",
        "Behind-the-scenes founder life — running an agency in Toronto, honest day-in-the-life",
        "Contrarian hot take backed by a specific client case study or data point",
        "Agency building lessons — pricing, hiring, scope creep, client management",
        "E-commerce industry trend — TikTok Shop, Amazon private label, Shopify ecosystem changes",
        "Founder vulnerability — a real mistake, failure, or struggle and what you learned",
        "Klaviyo email/SMS strategy that drove measurable revenue for a client",
        "Amazon or marketplace strategy — PPC, listings, A+ content, multi-channel",
        "CRO teardown — specific checkout, homepage, or landing page change that moved the needle",
        "Paid ads insight — Meta, TikTok, Google Ads scaling, ROAS benchmarks from client work",
        "Customer retention and LTV strategies that most brands overlook",
        "Shopify tech stack optimization — apps, integrations, speed improvements",
        "Podcast appearance recap or key insight from a conversation",
        "Pattern you've noticed across multiple clients that separates brands that scale vs. stall",
    ]
    selected_category = _random.choice(categories)

    # Hook styles proven to drive engagement
    hook_styles = [
        "bold statement with a specific number (e.g., 'We turned $40K/mo into $180K/mo for a skincare brand.')",
        "personal / behind-the-scenes (e.g., 'I almost closed my company in year 3.')",
        "story opening with tension (e.g., 'A client called me at 11pm last Tuesday. Their ROAS had dropped to 0.6x.')",
        "contrarian with proof (e.g., 'Stop split-testing your landing pages. Here's what to do instead.')",
        "curiosity gap (e.g., 'The #1 reason supplement brands plateau at $500K/mo isn't what you think.')",
        "data-led (e.g., 'We analyzed 200 CTAs across 15 Shopify stores. The winner surprised everyone.')",
    ]
    selected_hook = _random.choice(hook_styles)

    # Load soul.md for brand context
    from pathlib import Path as _Path
    _soul_path = _Path(__file__).resolve().parent.parent / "soul" / "soul.md"
    _soul_ctx = _soul_path.read_text(encoding="utf-8") if _soul_path.exists() else "No soul.md found"

    prompt = f"""You are a LinkedIn content strategist. Use the brand profile below to stay in character.

BRAND PROFILE:
{_soul_ctx}

Suggest ONE specific LinkedIn post idea for this category:
CATEGORY: {selected_category}

Use this hook style: {selected_hook}

Requirements:
- Include at least one specific number, dollar amount, or timeframe
- Write from the agency owner perspective (say "our client" or "a brand we work with")
- Make it feel like a real insight from real experience, not generic advice
- Do NOT suggest anything about Black Friday, Cyber Monday, or holiday sales unless it's currently November
- Focus on evergreen or currently relevant topics

Return ONLY the topic idea in 1-2 sentences. No explanations, no options, just one great idea."""

    try:
        message = client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=200,
            temperature=0.95,
            messages=[{"role": "user", "content": prompt}],
        )
        topic = message.content[0].text.strip()
        return {"topic": topic}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/idea/topic-library")
async def api_topic_library():
    """Return a curated library of topic ideas organized by category."""
    library = [
        {
            "category": "AI Tools & Agency Work",
            "icon": "robot",
            "color": "purple",
            "topics": [
                "Claude just wrote 47 email flows for a client in 2 hours. Here's what a human would've missed.",
                "I replaced 3 full-time roles at my company with AI tools. Here's the honest breakdown.",
                "My client asked me to cut our retainer by 40% because of AI. Here's what I told them.",
                "The AI stack that runs a $5M supplement brand's marketing (tools + costs breakdown)",
                "We used AI to audit 500 product pages in a day. It found $200K in missed revenue.",
                "Every agency owner is worried about AI replacing them. Here's why I'm not.",
            ],
        },
        {
            "category": "Client Case Studies",
            "icon": "chart",
            "color": "green",
            "topics": [
                "We took a skincare brand from $200K/yr to $1.2M in 11 months. The 3 changes that mattered.",
                "A client came to us spending $40K/mo on Meta Ads with 1.2x ROAS. 90 days later: 4.1x. Here's the system.",
                "One email flow change added $180K in annual revenue for a supplement brand. It took 45 minutes.",
                "We audited a Shopify store and found $300K in leaked revenue. The 5 holes we plugged.",
                "Last month we managed $500K in Google Ads spend across 8 brands. $13M in revenue. Here's what they all have in common.",
                "A DTC brand came to us with a 1.8% conversion rate. We got it to 4.2% without changing a single product.",
            ],
        },
        {
            "category": "Founder & Behind-the-Scenes",
            "icon": "person",
            "color": "blue",
            "topics": [
                "A day in the life running a marketing agency in Toronto (the unfiltered version)",
                "I almost closed my company in year 3. What changed my mind.",
                "The client call that changed how I run my entire agency",
                "8 years of running my business — the 5 decisions that actually mattered",
                "The loneliest part of running an agency that nobody talks about",
                "I had a panic attack before a client pitch last month. Here's what I learned.",
            ],
        },
        {
            "category": "Contrarian Takes",
            "icon": "lightning",
            "color": "orange",
            "topics": [
                "Stop split-testing your landing pages. Here's what to do instead (+ client results).",
                "Klaviyo isn't an email tool. Brands making $500K+/mo from it treat it as something completely different.",
                "Your Amazon PPC is probably profitable — and still killing your brand. Here's the math.",
                "I tell clients to STOP posting on social media. Here's why (and what we do instead).",
                "Most Shopify stores don't have a traffic problem. They have a conversion problem disguised as a traffic problem.",
                "The best-performing Meta Ad we ran last quarter had no video, no carousel, and no hook. Just a screenshot.",
            ],
        },
        {
            "category": "Agency Building",
            "icon": "building",
            "color": "indigo",
            "topics": [
                "The pricing model change that doubled our revenue",
                "Why I fired our biggest client (and what happened after)",
                "3 things I'd do differently if I started my agency today",
                "How we handle scope creep — the system that saved our margins",
                "I stopped selling retainers. Revenue went up 60%. Here's the model we switched to.",
                "The hiring mistake that cost me $80K and 6 months. What I screen for now.",
            ],
        },
        {
            "category": "E-commerce Trends",
            "icon": "trending",
            "color": "red",
            "topics": [
                "TikTok Shop is eating Amazon's lunch in supplements. Here's the data.",
                "The DTC brands that survive 2026 will all have this one thing in common.",
                "Shopify just made a move that will bankrupt half the apps in their ecosystem.",
                "Why every supplement brand should be terrified of Amazon's private label expansion.",
                "The subscription model is dying in DTC. Here's what's replacing it.",
                "Everyone's talking about AI in marketing. Nobody's talking about AI in fulfillment. That's the real play.",
            ],
        },
        {
            "category": "Klaviyo & Email/SMS",
            "icon": "email",
            "color": "teal",
            "topics": [
                "The 3 Klaviyo flows that generate 40% of revenue for our best-performing clients.",
                "We A/B tested 100 subject lines across 12 brands. The pattern that wins every time.",
                "Most brands treat SMS like email. That's why their unsubscribe rate is 10x higher than ours.",
                "A client's welcome flow was generating $2K/mo. We rebuilt it. Now it does $18K/mo. Same list size.",
                "The abandoned cart flow is NOT your highest-revenue automation. This one is.",
                "Stop sending 'Hey {first_name}' emails. Here's what actually drives opens in 2026.",
            ],
        },
        {
            "category": "CRO & Conversion",
            "icon": "target",
            "color": "emerald",
            "topics": [
                "I just audited 5 Shopify checkout pages. Every single one had this $50K mistake.",
                "The homepage change that increased a client's revenue by 34% (screenshot breakdown)",
                "We tested 200 CTAs across client stores. The winner surprised everyone.",
                "Your product page is losing you money. The 3 changes that took a brand from 1.5% to 3.8% conversion.",
                "The 'add to cart' button isn't the problem. The 3 seconds before it is.",
                "We removed social proof from a landing page. Conversion went UP. Here's why.",
            ],
        },
        {
            "category": "Amazon & Marketplaces",
            "icon": "store",
            "color": "amber",
            "topics": [
                "The Amazon listing audit that turned a $200K brand into an $800K brand (before + after)",
                "We analyzed 100 supplement listings on Amazon. The top 10% all do this one thing.",
                "Your Amazon A+ Content is probably costing you sales. Here's what converts.",
                "The multi-channel mistake that's killing your margins. Amazon + Shopify done right.",
                "We cut a client's Amazon ad spend by 35% and revenue went UP. The counterintuitive strategy.",
                "Amazon's algorithm changed again. Here's what's working for our clients in March 2026.",
            ],
        },
        {
            "category": "Paid Ads & Media Buying",
            "icon": "megaphone",
            "color": "pink",
            "topics": [
                "We spent $2M on Meta Ads last quarter across 12 brands. The 3 patterns that scaled.",
                "The $500/day Meta Ad that outperformed our $5,000/day campaign. Why more spend ≠ more results.",
                "TikTok Ads vs Meta Ads for supplements in 2026 — real data from 6 brands we manage.",
                "Google Ads for e-commerce is underpriced right now. Here's why we're shifting 30% of client budgets.",
                "The creative testing framework that cut our client's CPA by 40% in 60 days.",
                "I told a client to STOP running ads for 30 days. Their revenue went up. Here's the math.",
            ],
        },
    ]
    return {"library": library}


# ── Learning System API ─────────────────────────────────────

@router.get("/api/learnings")
async def api_get_learnings(db: Session = Depends(get_db)):
    """Return all active learning insights."""
    from database.models import LearningInsight
    insights = (
        db.query(LearningInsight)
        .filter(LearningInsight.is_active == True)
        .order_by(LearningInsight.confidence.desc(), LearningInsight.created_at.desc())
        .all()
    )
    return [
        {
            "id": i.id,
            "category": i.category.value,
            "source": i.source.value,
            "insight_text": i.insight_text,
            "prompt_directive": i.prompt_directive,
            "confidence": round(i.confidence, 2),
            "sample_size": i.sample_size,
            "times_used": i.times_used_in_prompts or 0,
            "created_at": i.created_at.isoformat() if i.created_at else None,
            "updated_at": i.updated_at.isoformat() if i.updated_at else None,
            "is_active": i.is_active,
        }
        for i in insights
    ]


@router.get("/api/learnings/all")
async def api_get_all_learnings(db: Session = Depends(get_db)):
    """Return all insights including deactivated ones."""
    from database.models import LearningInsight
    insights = (
        db.query(LearningInsight)
        .order_by(LearningInsight.created_at.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id": i.id,
            "category": i.category.value,
            "source": i.source.value,
            "insight_text": i.insight_text,
            "prompt_directive": i.prompt_directive,
            "confidence": round(i.confidence, 2),
            "sample_size": i.sample_size,
            "times_used": i.times_used_in_prompts or 0,
            "created_at": i.created_at.isoformat() if i.created_at else None,
            "is_active": i.is_active,
        }
        for i in insights
    ]


@router.post("/api/learnings/analyze")
async def api_run_analysis(db: Session = Depends(get_db)):
    """Trigger a full pattern analysis cycle."""
    from analytics.pattern_analyzer import PatternAnalyzer
    analyzer = PatternAnalyzer(db)
    results = analyzer.run_full_analysis()
    return {"status": "complete", "results": results}


@router.post("/api/learnings/{insight_id}/deactivate")
async def api_deactivate_insight(insight_id: int, db: Session = Depends(get_db)):
    """Manually deactivate an insight."""
    from database.models import LearningInsight
    insight = db.query(LearningInsight).filter(LearningInsight.id == insight_id).first()
    if not insight:
        return JSONResponse({"error": "Insight not found"}, status_code=404)
    insight.is_active = False
    db.commit()
    return {"status": "deactivated", "id": insight_id}


@router.post("/api/learnings/{insight_id}/activate")
async def api_activate_insight(insight_id: int, db: Session = Depends(get_db)):
    """Re-activate a deactivated insight."""
    from database.models import LearningInsight
    insight = db.query(LearningInsight).filter(LearningInsight.id == insight_id).first()
    if not insight:
        return JSONResponse({"error": "Insight not found"}, status_code=404)
    insight.is_active = True
    db.commit()
    return {"status": "activated", "id": insight_id}


@router.get("/api/learnings/history")
async def api_analysis_history(db: Session = Depends(get_db)):
    """Return analysis run history."""
    from database.models import AnalysisRun
    runs = db.query(AnalysisRun).order_by(AnalysisRun.created_at.desc()).limit(20).all()
    return [
        {
            "id": r.id,
            "run_type": r.run_type,
            "posts_analyzed": r.posts_analyzed,
            "insights_created": r.insights_created,
            "insights_updated": r.insights_updated,
            "insights_superseded": r.insights_superseded,
            "duration_seconds": r.run_duration_seconds,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in runs
    ]


# ── Autoresearch / Experiments ──────────────────────────────────


@router.get("/experiments", response_class=HTMLResponse)
async def experiments_page(request: Request, db: Session = Depends(get_db)):
    tm = TokenManager(db)
    auth_status = tm.get_token_status()
    return templates.TemplateResponse(
        "experiments.html",
        {"request": request, "auth_status": auth_status, "page": "experiments"},
    )


@router.get("/api/experiments")
async def api_list_experiments(db: Session = Depends(get_db)):
    """List all experiments with their variations."""
    from database.models import Experiment, ExperimentVariation
    experiments = (
        db.query(Experiment)
        .order_by(Experiment.created_at.desc())
        .limit(50)
        .all()
    )
    results = []
    for exp in experiments:
        variations = (
            db.query(ExperimentVariation)
            .filter(ExperimentVariation.experiment_id == exp.id)
            .order_by(ExperimentVariation.virality_score.desc())
            .all()
        )
        results.append({
            "id": exp.id,
            "type": exp.experiment_type.value if exp.experiment_type else None,
            "topic": exp.topic,
            "hypothesis": exp.hypothesis,
            "dimension_tested": exp.dimension_tested,
            "winner_score": exp.winner_score,
            "score_spread": exp.score_spread,
            "variations_count": exp.variations_count,
            "queued_post_id": exp.queued_post_id,
            "actual_engagement": exp.actual_engagement_score,
            "calibration_delta": exp.calibration_delta,
            "created_at": exp.created_at.isoformat() if exp.created_at else None,
            "variations": [
                {
                    "id": v.id,
                    "label": v.variation_label,
                    "parameter_value": v.parameter_value,
                    "content": v.content,
                    "virality_score": v.virality_score,
                    "is_winner": v.is_winner,
                    "hook_type": v.hook_type,
                    "template_name": v.template_name,
                    "tone": v.tone,
                    "word_count": v.word_count,
                }
                for v in variations
            ],
        })
    return results


@router.get("/api/experiments/summary")
async def api_experiments_summary(db: Session = Depends(get_db)):
    """Get experiment summary with win rates."""
    from autoresearch.log import ExperimentLog
    log = ExperimentLog(db)
    return {
        "summary": log.get_summary(),
        "win_rates": log.get_win_rates(),
    }


@router.post("/api/autoresearch/run")
async def api_run_autoresearch(db: Session = Depends(get_db)):
    """Manually trigger an autoresearch experiment cycle."""
    from autoresearch.runner import ExperimentRunner
    runner = ExperimentRunner(db)
    results = runner.run_experiment_cycle()
    return {
        "experiments_run": len(results),
        "results": results,
    }


# ── Commenting / Engagement API routes ───────────────────────────


@router.get("/api/commenting/targets")
async def api_commenting_targets(db: Session = Depends(get_db)):
    """Get today's commenting targets — high-engagement competitor posts."""
    from engagement.comment_helper import CommentHelper
    helper = CommentHelper(db)
    return {
        "targets": helper.get_daily_targets(count=15),
        "stats": helper.get_commenting_stats(),
    }


@router.post("/api/commenting/{post_id}/draft")
async def api_draft_comment(post_id: int, db: Session = Depends(get_db)):
    """Generate a comment draft for a competitor post."""
    from engagement.comment_helper import CommentHelper
    helper = CommentHelper(db)
    result = helper.draft_comment(post_id)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result


@router.post("/api/commenting/{post_id}/done")
async def api_mark_commented(post_id: int, db: Session = Depends(get_db)):
    """Mark a competitor post as commented on."""
    from engagement.comment_helper import CommentHelper
    helper = CommentHelper(db)
    if helper.mark_commented(post_id):
        return {"status": "marked", "id": post_id}
    return JSONResponse({"error": "Post not found"}, status_code=404)


# ── Hook Library API routes ──────────────────────────────────────


@router.get("/api/hooks")
async def api_get_hooks(db: Session = Depends(get_db)):
    """Get all hooks in the library."""
    from database.models import HookEntry
    hooks = db.query(HookEntry).order_by(HookEntry.engagement_score.desc()).all()
    return {
        "hooks": [
            {
                "id": h.id,
                "text": h.text,
                "hook_type": h.hook_type,
                "source": h.source,
                "engagement_score": h.engagement_score,
                "topic_category": h.topic_category,
                "times_used": h.times_used or 0,
                "last_used_at": h.last_used_at.isoformat() if h.last_used_at else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in hooks
        ],
        "total": len(hooks),
    }


@router.post("/api/hooks/extract")
async def api_extract_hooks(db: Session = Depends(get_db)):
    """Manually trigger hook extraction from top posts."""
    from content.hook_library import HookLibrary
    lib = HookLibrary(db)
    results = lib.run_extraction()
    return results


@router.post("/api/hooks/add")
async def api_add_hook(body: dict, db: Session = Depends(get_db)):
    """Manually add a hook to the library."""
    from content.hook_library import HookLibrary
    lib = HookLibrary(db)
    text = body.get("text", "").strip()
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)
    hook = lib.add_manual_hook(
        text=text,
        hook_type=body.get("hook_type", ""),
        topic=body.get("topic", ""),
    )
    return {"status": "added", "id": hook.id}


@router.delete("/api/hooks/{hook_id}")
async def api_delete_hook(hook_id: int, db: Session = Depends(get_db)):
    """Delete a hook from the library."""
    from database.models import HookEntry
    hook = db.query(HookEntry).filter(HookEntry.id == hook_id).first()
    if not hook:
        return JSONResponse({"error": "Hook not found"}, status_code=404)
    db.delete(hook)
    db.commit()
    return {"status": "deleted", "id": hook_id}


# ── Content Recycling API routes ──────────────────────────────────


@router.get("/api/recycling/candidates")
async def api_recycling_candidates(db: Session = Depends(get_db)):
    """Get posts eligible for content recycling."""
    from content.recycler import ContentRecycler
    recycler = ContentRecycler(db)
    candidates = recycler.find_recyclable_posts(limit=20)
    return {"candidates": candidates}


@router.post("/api/recycling/{post_id}/recycle")
async def api_recycle_post(post_id: int, db: Session = Depends(get_db)):
    """Recycle a top-performing post into a fresh version."""
    from content.recycler import ContentRecycler
    recycler = ContentRecycler(db)
    result = recycler.recycle_post(post_id)
    if "error" in result:
        return JSONResponse(result, status_code=400)
    return result
