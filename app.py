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

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database.engine import init_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    # Startup
    init_database()

    # Start scheduler (Phase 7)
    from post_queue.scheduler import start_scheduler

    scheduler = start_scheduler()

    yield

    # Shutdown
    scheduler.shutdown(wait=False)


app = FastAPI(title="LinkedIn Content Engine", lifespan=lifespan)

# Static files
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")

# Include routes
from dashboard.routes import router as dashboard_router

app.include_router(dashboard_router)

# Auth routes
from auth.linkedin_oauth import router as auth_router

app.include_router(auth_router, prefix="/auth")


if __name__ == "__main__":
    import uvicorn
    from config import settings

    uvicorn.run("app:app", host=settings.HOST, port=settings.PORT, reload=True)
