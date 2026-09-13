"""Background job scheduler — research, generation, posting and learning cycles.

Most jobs call synchronous code (Claude, Apify, SQLAlchemy). They run in a
worker thread via asyncio.to_thread so they never freeze the dashboard or the
posting job, which share this event loop.
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database.engine import SessionLocal
from database.models import PostStatus, QueuedPost

logger = logging.getLogger(__name__)


def _run_with_db(name: str, fn) -> None:
    """Run fn(db) with a fresh session, logging failures."""
    db = SessionLocal()
    try:
        fn(db)
    except Exception:
        logger.exception("%s failed", name)
    finally:
        db.close()


def _research(db) -> None:
    from research.research_engine import ResearchEngine
    items = ResearchEngine(db).run_research_cycle()
    logger.info("Research cycle stored %d items", len(items))


def _generation(db) -> None:
    queued = db.query(QueuedPost).filter(QueuedPost.status == PostStatus.QUEUED).count()
    if queued >= settings.MIN_QUEUE_SIZE:
        logger.info("Queue has %d posts, skipping generation", queued)
        return
    from content.generator import ContentGenerator
    batch = min(settings.MIN_QUEUE_SIZE - queued, 5)
    posts = ContentGenerator(db).generate_batch(count=batch)
    logger.info("Generated %d new posts (queue was at %d)", len(posts), queued)


def _competitor_scrape(db) -> None:
    if not settings.APIFY_TOKEN:
        return
    from research.competitor_scraper import CompetitorScraper
    r = CompetitorScraper(db).scrape_all_competitors()
    logger.info("Competitor scrape: %d scraped, %d new, %d analyzed", r["scraped"], r["new_posts"], r["analyzed"])


def _profile_scrape(db) -> None:
    if not (settings.APIFY_TOKEN and settings.LINKEDIN_PROFILE_URL):
        return
    from research.profile_scraper import ProfileScraper
    r = ProfileScraper(db).scrape_my_profile()
    if "error" in r:
        logger.warning("Profile scrape skipped: %s", r["error"])
    else:
        logger.info("Profile scrape: %d new, %d updated", r["new_posts"], r["updated_posts"])


def _autoresearch(db) -> None:
    if not settings.AUTORESEARCH_ENABLED:
        return
    posted = db.query(QueuedPost).filter(QueuedPost.status == PostStatus.POSTED).count()
    if posted < settings.AUTORESEARCH_MIN_POSTED:
        logger.info("Autoresearch waiting: %d/%d posts published", posted, settings.AUTORESEARCH_MIN_POSTED)
        return
    from autoresearch.runner import ExperimentRunner
    results = ExperimentRunner(db).run_experiment_cycle()
    logger.info("Autoresearch: %d experiments", len(results))


def _hook_extraction(db) -> None:
    from content.hook_library import HookLibrary
    r = HookLibrary(db).run_extraction()
    logger.info("Hook extraction: %d own, %d competitor", r["own_added"], r["competitor_added"])


def _learning(db) -> None:
    from analytics.pattern_analyzer import PatternAnalyzer
    results = PatternAnalyzer(db).run_full_analysis()
    if results.get("skipped"):
        logger.info("Learning analysis skipped: %s", results.get("reason"))


async def research_cycle():
    await asyncio.to_thread(_run_with_db, "Research cycle", _research)


async def generation_cycle():
    await asyncio.to_thread(_run_with_db, "Generation cycle", _generation)


async def competitor_scrape_cycle():
    await asyncio.to_thread(_run_with_db, "Competitor scrape", _competitor_scrape)


async def profile_scrape_cycle():
    await asyncio.to_thread(_run_with_db, "Profile scrape", _profile_scrape)


async def autoresearch_cycle():
    await asyncio.to_thread(_run_with_db, "Autoresearch", _autoresearch)


async def hook_extraction_cycle():
    await asyncio.to_thread(_run_with_db, "Hook extraction", _hook_extraction)


async def learning_analysis_cycle():
    await asyncio.to_thread(_run_with_db, "Learning analysis", _learning)


async def posting_cycle():
    """Publish due scheduled posts, then the next approved post if in a slot."""
    db = SessionLocal()
    try:
        from linkedin.poster import LinkedInPoster
        poster = LinkedInPoster(db)
        posted_ids = await poster.post_due_scheduled()
        if posted_ids:
            logger.info("Posted scheduled posts: %s", posted_ids)
        posted_id = await poster.post_next_approved()
        if posted_id:
            logger.info("Posted approved post: %s", posted_id)
    except Exception:
        logger.exception("Posting cycle failed")
    finally:
        db.close()


async def engagement_fetch_cycle():
    """Pull likes/comments for published posts (needs the r_member_social scope)."""
    db = SessionLocal()
    try:
        from auth.token_manager import TokenManager
        if not TokenManager(db).get_token_status().get("has_read_scope"):
            return
        from analytics.performance_tracker import PerformanceTracker
        updated = await PerformanceTracker(db).fetch_engagement_from_linkedin()
        logger.info("Engagement fetch updated %d posts", updated)
    except Exception:
        logger.exception("Engagement fetch failed")
    finally:
        db.close()


async def token_refresh_check():
    """Refresh the OAuth token if it expires within 7 days and can be refreshed."""
    db = SessionLocal()
    try:
        from auth.token_manager import TokenManager
        tm = TokenManager(db)
        if not tm.needs_refresh():
            return
        current = tm.get_current_token()
        if not (current and current.refresh_token):
            logger.warning("Token expires soon and has no refresh token — reconnect LinkedIn")
            return
        import httpx
        from auth.linkedin_oauth import TOKEN_URL
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": current.refresh_token,
                    "client_id": settings.LINKEDIN_CLIENT_ID,
                    "client_secret": settings.LINKEDIN_CLIENT_SECRET,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if response.status_code == 200:
            data = response.json()
            tm.update_token(
                access_token=data["access_token"],
                expires_in=data.get("expires_in", 5184000),
                refresh_token=data.get("refresh_token"),
                refresh_token_expires_in=data.get("refresh_token_expires_in"),
            )
            logger.info("OAuth token refreshed")
        else:
            logger.error("Token refresh failed: %s", response.status_code)
    except Exception:
        logger.exception("Token refresh check failed")
    finally:
        db.close()


async def engage_publish_cycle():
    """Publish at most one approved comment or reply that is due (engagement/publisher.py)."""
    db = SessionLocal()
    try:
        from engagement.publisher import publish_due
        result = await publish_due(db)
        if result:
            logger.info("Engage publish: %s", result)
    except Exception:
        logger.exception("Engage publish cycle failed")
    finally:
        db.close()


def start_scheduler() -> AsyncIOScheduler:
    """Configure and start all background jobs (cron times in POSTING_TIMEZONE)."""
    scheduler = AsyncIOScheduler(timezone=settings.POSTING_TIMEZONE)

    def interval(fn, job_id, **every):
        scheduler.add_job(fn, "interval", id=job_id, name=job_id, max_instances=1, coalesce=True, **every)

    def cron(fn, job_id, hour, minute=0):
        scheduler.add_job(fn, "cron", id=job_id, name=job_id, hour=hour, minute=minute, max_instances=1, coalesce=True)

    interval(research_cycle, "research_cycle", hours=settings.RESEARCH_INTERVAL_HOURS)
    interval(generation_cycle, "generation_cycle", hours=settings.GENERATION_INTERVAL_HOURS)
    interval(posting_cycle, "posting_cycle", minutes=5)
    interval(engage_publish_cycle, "engage_publish", minutes=1)
    cron(token_refresh_check, "token_refresh", hour=0)
    cron(engagement_fetch_cycle, "engagement_fetch", hour=7, minute=30)

    if settings.COMPETITOR_SCRAPE_ENABLED:
        cron(competitor_scrape_cycle, "competitor_scrape", hour=settings.COMPETITOR_SCRAPE_HOUR)
    if settings.PROFILE_SCRAPE_ENABLED:
        cron(profile_scrape_cycle, "profile_scrape", hour=settings.PROFILE_SCRAPE_HOUR)
    if settings.LEARNING_ANALYSIS_ENABLED:
        cron(learning_analysis_cycle, "learning_analysis", hour=8, minute=30)
    if settings.HOOK_LIBRARY_ENABLED:
        cron(hook_extraction_cycle, "hook_extraction", hour=9)
    # Always registered; the job itself checks AUTORESEARCH_ENABLED (editable in Settings).
    interval(autoresearch_cycle, "autoresearch_cycle", hours=settings.AUTORESEARCH_INTERVAL_HOURS)

    scheduler.start()
    logger.info("Scheduler started (%s)", settings.POSTING_TIMEZONE)
    return scheduler
