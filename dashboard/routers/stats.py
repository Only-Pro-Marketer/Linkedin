"""History: record a published post's LinkedIn numbers by hand.

Without the restricted r_member_social permission the app can't read stats
from LinkedIn, so these numbers are what Learnings and Analytics learn from.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.engine import get_db
from database.models import PostPerformance, PostStatus, QueuedPost

router = APIRouter(tags=["stats"])


class ManualStats(BaseModel):
    impressions: int = Field(0, ge=0, le=100_000_000)
    likes: int = Field(0, ge=0, le=10_000_000)
    comments: int = Field(0, ge=0, le=10_000_000)
    shares: int = Field(0, ge=0, le=10_000_000)


@router.post("/api/history/{post_id}/stats")
def save_stats(post_id: int, body: ManualStats, db: Session = Depends(get_db)):
    post = db.get(QueuedPost, post_id)
    if not post:
        return JSONResponse({"error": "Post not found"}, status_code=404)
    if post.status != PostStatus.POSTED:
        return JSONResponse({"error": "Only published posts have stats"}, status_code=400)
    perf = post.performance or PostPerformance(post_id=post.id)
    perf.impressions, perf.likes, perf.comments, perf.shares = body.impressions, body.likes, body.comments, body.shares
    perf.last_checked = datetime.utcnow()
    db.add(perf)
    db.commit()
    return {"id": post.id, **body.model_dump()}
