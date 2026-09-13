"""LinkedIn Content Engine — FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s:%(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("posting.log"),
    ],
)

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from config import LOOPBACK_HOSTS, get_secret_key, settings  # noqa: E402
from dashboard.security import LoginRequiredMiddleware, SameOriginMiddleware  # noqa: E402
from database.engine import SessionLocal, init_database  # noqa: E402

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: DB + migrations, UI settings, crash recovery, scheduler."""
    init_database()

    from app_settings import apply_overrides
    apply_overrides()

    from engagement.publisher import recover_stale
    from linkedin.poster import recover_stale_posts
    db = SessionLocal()
    try:
        recover_stale_posts(db)
        recover_stale(db)
    finally:
        db.close()

    scheduler = None
    if settings.SCHEDULER_ENABLED:
        from post_queue.scheduler import start_scheduler
        scheduler = start_scheduler()

    yield

    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="LinkedIn Content Engine", lifespan=lifespan)

# Middleware runs outermost-last-added: session → CSRF check → login check → routes
app.add_middleware(LoginRequiredMiddleware)
app.add_middleware(SameOriginMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=get_secret_key(),
    session_cookie="ce_session",
    same_site="lax",
    max_age=14 * 24 * 3600,
)

app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")

from dashboard.security import router as security_router  # noqa: E402
from dashboard.routes import router as dashboard_router  # noqa: E402
from dashboard.routers.quality import router as quality_router  # noqa: E402
from dashboard.routers.home import router as home_router  # noqa: E402
from dashboard.routers.brand import router as brand_router  # noqa: E402
from dashboard.routers.studio import router as studio_router  # noqa: E402
from dashboard.routers.engage import router as engage_router  # noqa: E402
from dashboard.routers.plan import router as plan_router  # noqa: E402
from dashboard.routers.profile import router as profile_router  # noqa: E402
from dashboard.routers.settings import router as settings_router  # noqa: E402
from dashboard.routers.stats import router as stats_router  # noqa: E402
from auth.linkedin_oauth import router as auth_router  # noqa: E402

app.include_router(security_router)
app.include_router(home_router)
app.include_router(brand_router)
app.include_router(studio_router)
app.include_router(engage_router)
app.include_router(plan_router)
app.include_router(profile_router)
app.include_router(settings_router)
app.include_router(stats_router)
app.include_router(quality_router)
app.include_router(dashboard_router)
app.include_router(auth_router, prefix="/auth")


def check_bind_safety() -> None:
    """Refuse to expose an unauthenticated dashboard to the network."""
    if settings.HOST not in LOOPBACK_HOSTS and not settings.DASHBOARD_PASSWORD:
        raise SystemExit(
            f"Refusing to listen on {settings.HOST} without a password. "
            "Set DASHBOARD_PASSWORD in .env, or use HOST=127.0.0.1."
        )


if __name__ == "__main__":
    import uvicorn

    check_bind_safety()
    uvicorn.run("app:app", host=settings.HOST, port=settings.PORT, reload=settings.RELOAD)
