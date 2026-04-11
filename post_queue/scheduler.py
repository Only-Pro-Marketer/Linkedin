"""Background job scheduler — runs research, generation, and posting cycles."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database.engine import SessionLocal
from database.models import PostStatus, QueuedPost

logger = logging.getLogger(__name__)


def _get_db():
    """Create a fresh DB session for background jobs."""
    return SessionLocal()


async def research_cycle():
    """Fetch trends, Reddit, news, and store ranked topics."""
    logger.info("Running research cycle...")
    db = _get_db()
    try:
        from research.research_engine import ResearchEngine

        engine = ResearchEngine(db)
        items = engine.run_research_cycle()
        logger.info("Research cycle stored %d items", len(items))
    except Exception as e:
        logger.error("Research cycle failed: %s", e)
    finally:
        db.close()


async def generation_cycle():
    """Generate new posts if queue is running low."""
    logger.info("Running generation cycle...")
    db = _get_db()
    try:
        # Check current queue size
        queued_count = (
            db.query(QueuedPost)
            .filter(QueuedPost.status == PostStatus.QUEUED)
            .count()
        )

        if queued_count >= settings.MIN_QUEUE_SIZE:
            logger.info("Queue has %d posts, skipping generation", queued_count)
            return

        # Generate a batch
        from content.generator import ContentGenerator

        generator = ContentGenerator(db)
        needed = settings.MIN_QUEUE_SIZE - queued_count
        batch_size = min(needed, 5)
        posts = generator.generate_batch(count=batch_size)
        logger.info("Generated %d new posts (queue was at %d)", len(posts), queued_count)
    except Exception as e:
        logger.error("Generation cycle failed: %s", e)
    finally:
        db.close()


async def posting_cycle():
    """Post scheduled and approved posts when their time arrives."""
    logger.info("Running posting cycle...")
    db = _get_db()
    try:
        from linkedin.poster import LinkedInPoster

        poster = LinkedInPoster(db)

        # First: post any scheduled posts that are due
        posted_ids = await poster.post_due_scheduled()
        if posted_ids:
            logger.info("Posted %d scheduled posts: %s", len(posted_ids), posted_ids)

        # Then: post the next approved post if a slot is available
        posted_id = await poster.post_next_approved()
        if posted_id:
            logger.info("Posted approved post: %s", posted_id)
    except Exception as e:
        logger.error("Posting cycle failed: %s", e)
    finally:
        db.close()


async def competitor_scrape_cycle():
    """Daily scrape of all tracked competitors' LinkedIn profiles and posts."""
    logger.info("Running competitor scrape cycle...")
    db = _get_db()
    try:
        from research.competitor_scraper import CompetitorScraper

        scraper = CompetitorScraper(db)
        results = scraper.scrape_all_competitors()
        logger.info(
            "Competitor scrape complete: %d scraped, %d new posts, %d analyzed",
            results["scraped"], results["new_posts"], results["analyzed"],
        )
    except Exception as e:
        logger.error("Competitor scrape cycle failed: %s", e)
    finally:
        db.close()


async def profile_scrape_cycle():
    """Daily scrape of the user's own LinkedIn profile and posts."""
    logger.info("Running profile scrape cycle...")
    db = _get_db()
    try:
        from research.profile_scraper import ProfileScraper

        scraper = ProfileScraper(db)
        result = scraper.scrape_my_profile()
        if "error" in result:
            logger.warning("Profile scrape skipped: %s", result["error"])
        else:
            logger.info(
                "Profile scrape complete: %d new, %d updated, %d analyzed",
                result["new_posts"], result["updated_posts"], result["analyzed"],
            )
    except Exception as e:
        logger.error("Profile scrape cycle failed: %s", e)
    finally:
        db.close()


async def token_refresh_check():
    """Check if the OAuth token needs refreshing."""
    logger.info("Checking OAuth token status...")
    db = _get_db()
    try:
        from auth.token_manager import TokenManager

        tm = TokenManager(db)
        if tm.needs_refresh():
            current = tm.get_current_token()
            if current and current.refresh_token:
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
                        logger.info("OAuth token refreshed successfully")
                    else:
                        logger.error("Token refresh failed: %s", response.text)
            else:
                logger.warning("Token needs refresh but no refresh token available")
    except Exception as e:
        logger.error("Token refresh check failed: %s", e)
    finally:
        db.close()


async def autoresearch_cycle():
    """Run autonomous experiments — generate variations, score, pick winners."""
    if not settings.AUTORESEARCH_ENABLED:
        return
    logger.info("Running autoresearch experiment cycle...")
    db = _get_db()
    try:
        from autoresearch.runner import ExperimentRunner

        runner = ExperimentRunner(db)
        results = runner.run_experiment_cycle()
        winners = [r for r in results if r.get("queued_post_id")]
        logger.info(
            "Autoresearch cycle complete: %d experiments, %d queued winners",
            len(results), len(winners),
        )
    except Exception as e:
        logger.error("Autoresearch cycle failed: %s", e)
    finally:
        db.close()


async def hook_extraction_cycle():
    """Extract winning hooks from top-performing posts into the hook library."""
    if not settings.HOOK_LIBRARY_ENABLED:
        return
    logger.info("Running hook extraction cycle...")
    db = _get_db()
    try:
        from content.hook_library import HookLibrary
        lib = HookLibrary(db)
        results = lib.run_extraction()
        logger.info(
            "Hook extraction complete: %d own, %d competitor, %d total",
            results["own_added"], results["competitor_added"], results["total_hooks"],
        )
    except Exception as e:
        logger.error("Hook extraction cycle failed: %s", e)
    finally:
        db.close()


async def learning_analysis_cycle():
    """Run pattern analysis and generate/update learning insights."""
    if not settings.LEARNING_ANALYSIS_ENABLED:
        return
    logger.info("Running learning analysis cycle...")
    db = _get_db()
    try:
        from analytics.pattern_analyzer import PatternAnalyzer

        analyzer = PatternAnalyzer(db)
        results = analyzer.run_full_analysis()
        if results.get("skipped"):
            logger.info("Learning analysis skipped: %s", results.get("reason"))
        else:
            total_created = sum(
                v.get("created", 0) for v in results.values() if isinstance(v, dict) and "created" in v
            )
            total_updated = sum(
                v.get("updated", 0) for v in results.values() if isinstance(v, dict) and "updated" in v
            )
            logger.info("Learning analysis complete: %d created, %d updated", total_created, total_updated)
    except Exception as e:
        logger.error("Learning analysis cycle failed: %s", e)
    finally:
        db.close()


def start_scheduler() -> AsyncIOScheduler:
    """Configure and start all background jobs."""
    scheduler = AsyncIOScheduler()

    # Research: every 6 hours
    scheduler.add_job(
        research_cycle,
        "interval",
        hours=settings.RESEARCH_INTERVAL_HOURS,
        id="research_cycle",
        name="Research Cycle",
    )

    # Generation: every 4 hours
    scheduler.add_job(
        generation_cycle,
        "interval",
        hours=settings.GENERATION_INTERVAL_HOURS,
        id="generation_cycle",
        name="Generation Cycle",
    )

    # Posting: every 5 minutes (granular for time-slot accuracy)
    # post_next_approved() only posts during ContentCalendar time windows
    scheduler.add_job(
        posting_cycle,
        "interval",
        minutes=5,
        id="posting_cycle",
        name="Posting Cycle",
    )

    # Token refresh: daily at midnight
    scheduler.add_job(
        token_refresh_check,
        "cron",
        hour=0,
        minute=0,
        id="token_refresh",
        name="Token Refresh Check",
    )

    # Competitor scraping: daily at configured hour (default 6 AM)
    if settings.COMPETITOR_SCRAPE_ENABLED:
        scheduler.add_job(
            competitor_scrape_cycle,
            "cron",
            hour=settings.COMPETITOR_SCRAPE_HOUR,
            minute=0,
            id="competitor_scrape",
            name="Competitor Scrape Cycle",
        )

    # My profile scraping: daily at configured hour (default 7 AM)
    if settings.PROFILE_SCRAPE_ENABLED and settings.LINKEDIN_PROFILE_URL:
        scheduler.add_job(
            profile_scrape_cycle,
            "cron",
            hour=settings.PROFILE_SCRAPE_HOUR,
            minute=0,
            id="profile_scrape",
            name="Profile Scrape Cycle",
        )

    # Learning analysis: daily at 8:30 AM (after engagement data is fresh)
    if settings.LEARNING_ANALYSIS_ENABLED:
        scheduler.add_job(
            learning_analysis_cycle,
            "cron",
            hour=8,
            minute=30,
            id="learning_analysis",
            name="Learning Analysis Cycle",
        )

    # Hook extraction: daily at 9 AM (after profile scrape brings fresh data)
    if settings.HOOK_LIBRARY_ENABLED:
        scheduler.add_job(
            hook_extraction_cycle,
            "cron",
            hour=9,
            minute=0,
            id="hook_extraction",
            name="Hook Extraction Cycle",
        )

    # Autoresearch: autonomous experiments every N hours
    if settings.AUTORESEARCH_ENABLED:
        scheduler.add_job(
            autoresearch_cycle,
            "interval",
            hours=settings.AUTORESEARCH_INTERVAL_HOURS,
            id="autoresearch_cycle",
            name="Autoresearch Experiment Cycle",
        )

    scheduler.start()
    logger.info("Scheduler started with all jobs")
    return scheduler
