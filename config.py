"""Application configuration loaded from environment variables."""

import secrets
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Claude API (all calls go through llm.py)
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-opus-5"
    CLAUDE_REFUSAL_FALLBACKS: bool = True  # server-side fallbacks (Claude API only)

    # LinkedIn OAuth
    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: str = ""
    LINKEDIN_REDIRECT_URI: str = "http://localhost:8000/auth/callback"
    # r_member_social is restricted (Community Management API). Add it here only
    # if LinkedIn approved your app for it — otherwise authorization fails.
    LINKEDIN_SCOPES: str = "openid profile w_member_social"
    LINKEDIN_API_VERSION: str = "202601"

    # Reddit (optional)
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "linkedin-post-generator/1.0"

    # Database
    DATABASE_URL: str = "sqlite:///database/linkedin_posts.db"

    # Scheduling
    SCHEDULER_ENABLED: bool = True
    POSTS_PER_DAY: int = 1  # hard cap on publishes per local day (all paths)
    MIN_HOURS_BETWEEN_POSTS: float = 3.0  # minimum gap between automatic publishes
    RESEARCH_INTERVAL_HOURS: int = 6
    GENERATION_INTERVAL_HOURS: int = 4
    MIN_QUEUE_SIZE: int = 10

    # Content
    TARGET_NICHE: str = "e-commerce growth agency (CRO, Klaviyo, Shopify, ads, Amazon)"
    DEFAULT_TONE: str = "authoritative"
    POST_WORD_MIN: int = 100
    POST_WORD_MAX: int = 300

    # Gemini (Nano Banana) Image Generation
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash-image"
    # kie.ai image generation (used instead of Gemini when KIE_API_KEY is set)
    KIE_API_KEY: str = ""
    KIE_IMAGE_MODEL: str = "google/nano-banana"
    KIE_IMAGE_ASPECT: str = "4:5"  # LinkedIn feed images work best at 1:1 or 4:5
    IMAGE_AUTO_GENERATE: bool = False

    # Video / GIF Generation
    GIF_AUTO_GENERATE: bool = False
    GIF_MAX_DURATION_SECONDS: int = 15
    GIF_MAX_FILE_SIZE_MB: int = 8
    GIF_FPS: int = 10
    VIDEO_STORAGE_DIR: str = "dashboard/static/videos/generated"

    # Screen Recording (headless browser visits a URL — off by default)
    SCREEN_RECORD_ENABLED: bool = False
    PLAYWRIGHT_HEADLESS: bool = True

    # Competitor Scraper (Apify LinkedIn Scrapers)
    APIFY_TOKEN: str = ""
    # Optional Engage helpers (fetch a post's text / its comments). Public actors
    # change over time, so both IDs can be swapped in .env.
    APIFY_POST_ACTOR: str = "supreme_coder/linkedin-post"
    APIFY_COMMENTS_ACTOR: str = "apimaestro/linkedin-post-comments-replies-engagements-scraper-no-cookies"
    COMPETITOR_SCRAPE_HOUR: int = 6  # daily scrape at 6 AM
    COMPETITOR_SCRAPE_ENABLED: bool = True

    # My Profile Scraper
    LINKEDIN_PROFILE_URL: str = ""
    PROFILE_SCRAPE_HOUR: int = 7  # daily scrape at 7 AM
    PROFILE_SCRAPE_ENABLED: bool = True

    # Fact-checking + quality
    FACT_CHECK_ENABLED: bool = True
    AUTO_REPAIR: bool = True  # one "Fix with AI" pass on new drafts that fail the quality check

    # Learning System
    LEARNING_ANALYSIS_ENABLED: bool = True
    LEARNING_MIN_POSTS_FOR_ANALYSIS: int = 5
    LEARNING_MAX_PROMPT_INSIGHTS: int = 8
    LEARNING_MIN_CONFIDENCE: float = 0.4

    # Autoresearch (Claude-scored experiments). Off until you have real results:
    # it also needs AUTORESEARCH_MIN_POSTED published posts before it runs.
    AUTORESEARCH_ENABLED: bool = False
    AUTORESEARCH_MIN_POSTED: int = 10
    AUTORESEARCH_VARIATIONS_PER_EXPERIMENT: int = 4
    AUTORESEARCH_MIN_SCORE_TO_QUEUE: int = 65
    AUTORESEARCH_EXPERIMENTS_PER_CYCLE: int = 3
    AUTORESEARCH_INTERVAL_HOURS: int = 8

    # Posting Time Optimization
    POSTING_TIMEZONE: str = "America/Toronto"

    # Content Strategy
    TEXT_ONLY_DEFAULT: bool = True

    # Hook Library
    HOOK_LIBRARY_ENABLED: bool = True

    # Content Recycling
    RECYCLING_MIN_AGE_DAYS: int = 60
    RECYCLING_MIN_ENGAGEMENT: int = 50

    # Engagement (comments / replies published via the LinkedIn API)
    ENGAGE_DAILY_CAP: int = 30

    # Dashboard
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    RELOAD: bool = False
    DASHBOARD_PASSWORD: str = ""  # required when HOST is not a loopback address
    SECRET_KEY: str = ""  # session signing key; generated on first run if empty

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def get_secret_key() -> str:
    """Return SECRET_KEY, generating and persisting one on first run."""
    if settings.SECRET_KEY:
        return settings.SECRET_KEY
    key_file = Path("database/.secret_key")
    if key_file.exists():
        return key_file.read_text().strip()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    key_file.write_text(key)
    key_file.chmod(0o600)
    return key
