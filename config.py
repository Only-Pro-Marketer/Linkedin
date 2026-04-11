"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Claude API
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"
    CLAUDE_TEMPERATURE: float = 0.8
    CLAUDE_MAX_TOKENS: int = 1500

    # LinkedIn OAuth
    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: str = ""
    LINKEDIN_REDIRECT_URI: str = "http://localhost:8000/auth/callback"

    # Reddit (optional)
    REDDIT_CLIENT_ID: str = ""
    REDDIT_CLIENT_SECRET: str = ""
    REDDIT_USER_AGENT: str = "linkedin-post-generator/1.0"

    # Database
    DATABASE_URL: str = "sqlite:///database/linkedin_posts.db"

    # Scheduling
    POSTS_PER_DAY: int = 4
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
    IMAGE_AUTO_GENERATE: bool = False

    # Video / GIF Generation
    GIF_AUTO_GENERATE: bool = False
    GIF_MAX_DURATION_SECONDS: int = 15
    GIF_MAX_FILE_SIZE_MB: int = 8
    GIF_FPS: int = 10
    VIDEO_STORAGE_DIR: str = "dashboard/static/videos/generated"

    # Screen Recording
    SCREEN_RECORD_ENABLED: bool = True
    PLAYWRIGHT_HEADLESS: bool = True

    # Competitor Scraper (Apify LinkedIn Scrapers)
    APIFY_TOKEN: str = ""
    COMPETITOR_SCRAPE_HOUR: int = 6  # daily scrape at 6 AM
    COMPETITOR_SCRAPE_ENABLED: bool = True

    # My Profile Scraper
    LINKEDIN_PROFILE_URL: str = ""
    PROFILE_SCRAPE_HOUR: int = 7  # daily scrape at 7 AM
    PROFILE_SCRAPE_ENABLED: bool = True

    # Fact-checking
    FACT_CHECK_ENABLED: bool = True
    FACT_CHECK_MODEL: str = "claude-sonnet-4-20250514"

    # Learning System
    LEARNING_ANALYSIS_ENABLED: bool = True
    LEARNING_MIN_POSTS_FOR_ANALYSIS: int = 5
    LEARNING_MAX_PROMPT_INSIGHTS: int = 8
    LEARNING_MIN_CONFIDENCE: float = 0.4

    # Autoresearch (Karpathy-style experimentation)
    AUTORESEARCH_ENABLED: bool = True
    AUTORESEARCH_VARIATIONS_PER_EXPERIMENT: int = 4
    AUTORESEARCH_MIN_SCORE_TO_QUEUE: int = 65
    AUTORESEARCH_EXPERIMENTS_PER_CYCLE: int = 3
    AUTORESEARCH_INTERVAL_HOURS: int = 8

    # Posting Time Optimization
    POSTING_TIMEZONE: str = "America/Toronto"
    POSTING_SLOTS: str = "08:00,10:00"
    POSTING_ACTIVE_DAYS: str = "0,1,2,3,4"  # Mon-Fri

    # Content Strategy
    TEXT_ONLY_DEFAULT: bool = True

    # Hook Library
    HOOK_LIBRARY_ENABLED: bool = True

    # Content Recycling
    CONTENT_RECYCLING_ENABLED: bool = True
    RECYCLING_MIN_AGE_DAYS: int = 60
    RECYCLING_MIN_ENGAGEMENT: int = 50

    # Dashboard
    HOST: str = "0.0.0.0"
    PORT: int = 8082

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()


# ── Shared Anthropic client singleton ──────────────────────────
_anthropic_client = None


def get_anthropic_client():
    """Return a shared Anthropic client instance (lazy-initialized)."""
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        _anthropic_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _anthropic_client
