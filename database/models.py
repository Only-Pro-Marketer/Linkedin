"""SQLAlchemy ORM models for the LinkedIn post generator."""

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class PostStatus(enum.Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    APPROVED = "approved"
    REJECTED = "rejected"
    SCHEDULED = "scheduled"
    POSTING = "posting"
    POSTED = "posted"
    FAILED = "failed"


class QueuedPost(Base):
    __tablename__ = "queued_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Content
    content = Column(Text, nullable=False)
    hook = Column(Text)
    hook_type = Column(String(50))
    body_format = Column(String(50))
    cta_type = Column(String(50))
    template_name = Column(String(100))
    word_count = Column(Integer)

    # Metadata
    status = Column(SQLEnum(PostStatus), default=PostStatus.QUEUED, index=True)
    topic = Column(String(200))
    research_context = Column(Text)
    research_item_id = Column(Integer, ForeignKey("research_items.id"), nullable=True, index=True)
    generation_prompt = Column(Text)

    # Scheduling
    scheduled_time = Column(DateTime, nullable=True)
    posted_at = Column(DateTime, nullable=True, index=True)

    # LinkedIn response
    linkedin_post_id = Column(String(200))
    linkedin_post_url = Column(String(500))

    # Image
    image_path = Column(String(500), nullable=True)
    image_prompt = Column(Text, nullable=True)
    has_image = Column(Boolean, default=False)

    # Video / GIF
    media_type = Column(String(20), default="none")  # none, image, gif, video
    video_path = Column(String(500), nullable=True)
    video_prompt = Column(Text, nullable=True)
    has_video = Column(Boolean, default=False)
    video_duration = Column(Integer, nullable=True)  # seconds
    video_source = Column(String(50), nullable=True)  # screen_record, programmatic, manual_upload

    # Fact-check
    fact_check_status = Column(String(50), default="not_checked")  # not_checked, pass, fail, warning
    fact_check_notes = Column(Text, nullable=True)
    fact_checked_at = Column(DateTime, nullable=True)

    # Virality score
    virality_score = Column(Integer, nullable=True)  # 1-100
    virality_breakdown = Column(Text, nullable=True)  # JSON breakdown
    virality_performance = Column(String(20), nullable=True)  # low/medium/high/viral

    # User actions
    user_edits = Column(Text, nullable=True)
    rejection_reason = Column(String(500))
    rejection_categories = Column(Text, nullable=True)  # JSON list of RejectionReason values

    # Content recycling
    recycled_from_id = Column(Integer, nullable=True)  # ID of original post this was recycled from

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    performance = relationship("PostPerformance", back_populates="post", uselist=False, lazy="joined")


class PostPerformance(Base):
    __tablename__ = "post_performance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, ForeignKey("queued_posts.id"), unique=True, index=True)

    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    impressions = Column(Integer, default=0)

    last_checked = Column(DateTime, default=datetime.utcnow)

    post = relationship("QueuedPost", back_populates="performance")


class ResearchItem(Base):
    __tablename__ = "research_items"

    id = Column(Integer, primary_key=True, autoincrement=True)

    source = Column(String(50), index=True)
    topic = Column(String(200))
    title = Column(String(500))
    content = Column(Text)
    url = Column(String(1000), nullable=True)
    relevance_score = Column(Float, default=0.0, index=True)
    used = Column(Boolean, default=False, index=True)
    saved = Column(Boolean, default=False, index=True)

    # Region and category for filtering
    region = Column(String(50), nullable=True, index=True)      # north_america, europe, uk, global
    category = Column(String(100), nullable=True, index=True)   # supplements, cro, shopify, klaviyo, amazon, paid_ads, tiktok_shop, dtc, agency, ecommerce_general

    # Visual research data
    screenshot_path = Column(String(500), nullable=True)
    data_points = Column(Text, nullable=True)  # JSON: extracted stats, numbers, case study data

    # User annotations
    notes = Column(Text, nullable=True)

    # Trending velocity tracking
    first_seen_at = Column(DateTime, nullable=True)
    appearance_count = Column(Integer, default=1)
    normalized_topic_key = Column(String(200), nullable=True, index=True)
    velocity = Column(String(20), nullable=True)  # "rising", "stable", "falling", "new"

    fetched_at = Column(DateTime, default=datetime.utcnow, index=True)


class TemplateRecord(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String(100), unique=True)
    hook_pattern = Column(Text)
    body_pattern = Column(Text)
    cta_pattern = Column(Text)
    fill_instructions = Column(Text)
    example_post = Column(Text)

    times_used = Column(Integer, default=0)
    avg_performance = Column(Float, default=0.0)

    created_at = Column(DateTime, default=datetime.utcnow)


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)

    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=True)
    token_type = Column(String(50), default="Bearer")
    expires_at = Column(DateTime, nullable=False)
    refresh_expires_at = Column(DateTime, nullable=True)
    scopes = Column(String(500))
    person_urn = Column(String(200))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ContentCalendar(Base):
    __tablename__ = "content_calendar"

    id = Column(Integer, primary_key=True, autoincrement=True)

    day_of_week = Column(Integer)  # 0=Monday, 6=Sunday
    time_slot = Column(String(5))  # "09:00", "12:30"
    is_active = Column(Boolean, default=True)

    preferred_template_type = Column(String(100), nullable=True)
    preferred_tone = Column(String(50), nullable=True)


class HookEntry(Base):
    """Accumulated winning hooks extracted from top-performing posts."""
    __tablename__ = "hook_library"

    id = Column(Integer, primary_key=True, autoincrement=True)

    text = Column(Text, nullable=False)
    hook_type = Column(String(50))  # question, story, statistic, contrarian, command
    source = Column(String(20), default="own")  # own, competitor, manual
    source_post_id = Column(Integer, nullable=True)  # ID of originating post

    engagement_score = Column(Integer, default=0)  # likes + comments*3 + shares*5
    topic_category = Column(String(200), nullable=True)

    times_used = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(Integer, primary_key=True, autoincrement=True)

    name = Column(String(200), nullable=False)
    linkedin_url = Column(String(500), nullable=True)
    linkedin_username = Column(String(200), nullable=True)  # extracted from URL
    niche = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)

    # Profile data (auto-fetched)
    profile_picture = Column(String(1000), nullable=True)
    headline = Column(String(500), nullable=True)
    follower_count = Column(Integer, default=0)

    # Tracked stats
    total_posts_tracked = Column(Integer, default=0)
    avg_likes = Column(Float, default=0.0)
    avg_comments = Column(Float, default=0.0)
    avg_shares = Column(Float, default=0.0)
    posting_frequency = Column(String(50), nullable=True)  # e.g. "3x/week"

    # Scraper status
    last_scraped_at = Column(DateTime, nullable=True)
    scrape_status = Column(String(50), default="pending")  # pending, success, failed
    scrape_error = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    posts = relationship("CompetitorPost", back_populates="competitor", cascade="all, delete-orphan")


class CompetitorPost(Base):
    __tablename__ = "competitor_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    competitor_id = Column(Integer, ForeignKey("competitors.id"), nullable=False, index=True)

    content = Column(Text, nullable=False)
    post_url = Column(String(500), nullable=True)
    linkedin_post_id = Column(String(200), nullable=True)  # dedup key from API
    post_date = Column(DateTime, nullable=True)

    # Engagement
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    impressions = Column(Integer, default=0)

    # Media
    has_image = Column(Boolean, default=False)
    has_video = Column(Boolean, default=False)
    image_url = Column(String(1000), nullable=True)

    # AI Analysis
    hook_style = Column(String(100), nullable=True)
    content_format = Column(String(100), nullable=True)  # list, story, question, etc.
    topic = Column(String(200), nullable=True)
    key_takeaway = Column(Text, nullable=True)
    why_it_works = Column(Text, nullable=True)
    how_to_recreate = Column(Text, nullable=True)  # AI recreation guide
    ai_analyzed = Column(Boolean, default=False)

    # Recreation
    is_saved = Column(Boolean, default=False)  # saved for inspiration
    recreated = Column(Boolean, default=False)  # already used to create a post

    # Engagement assistance
    commented_at = Column(DateTime, nullable=True)
    comment_draft = Column(Text, nullable=True)

    # Source
    source = Column(String(50), default="manual")  # manual or scraped

    created_at = Column(DateTime, default=datetime.utcnow)

    competitor = relationship("Competitor", back_populates="posts")


class MyLinkedInPost(Base):
    """Stores the user's own LinkedIn posts scraped via Apify."""
    __tablename__ = "my_linkedin_posts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    content = Column(Text, nullable=False)
    post_url = Column(String(500), nullable=True)
    linkedin_post_id = Column(String(200), nullable=True, unique=True)
    post_date = Column(DateTime, nullable=True)

    # Engagement
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    impressions = Column(Integer, default=0)

    # Media
    has_image = Column(Boolean, default=False)
    has_video = Column(Boolean, default=False)
    image_url = Column(String(1000), nullable=True)

    # AI Analysis
    hook_style = Column(String(100), nullable=True)
    content_format = Column(String(100), nullable=True)
    topic = Column(String(200), nullable=True)
    key_takeaway = Column(Text, nullable=True)
    why_it_works = Column(Text, nullable=True)
    ai_analyzed = Column(Boolean, default=False)

    # Tracking
    scraped_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# --- Learning System Models ---


class RejectionReason(enum.Enum):
    HOOK_TOO_WEAK = "hook_too_weak"
    OFF_BRAND = "off_brand"
    TOO_GENERIC = "too_generic"
    TOO_LONG = "too_long"
    TOO_SHORT = "too_short"
    NOT_ACTIONABLE = "not_actionable"
    WRONG_TONE = "wrong_tone"
    WRONG_TOPIC = "wrong_topic"
    FACTUALLY_WRONG = "factually_wrong"
    SOUNDS_AI = "sounds_ai"
    OTHER = "other"


class InsightCategory(enum.Enum):
    HOOK_STYLE = "hook_style"
    TONE = "tone"
    TOPIC = "topic"
    TEMPLATE = "template"
    ANGLE = "angle"
    FORMAT = "format"
    LENGTH = "length"
    TIMING = "timing"
    REJECTION_PATTERN = "rejection_pattern"
    EDIT_PATTERN = "edit_pattern"
    GENERAL = "general"


class InsightSource(enum.Enum):
    PERFORMANCE_ANALYSIS = "performance_analysis"
    REJECTION_ANALYSIS = "rejection_analysis"
    EDIT_ANALYSIS = "edit_analysis"
    MANUAL = "manual"


class LearningInsight(Base):
    """Accumulated learning from post performance, rejections, and edits."""
    __tablename__ = "learning_insights"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # What was learned
    category = Column(SQLEnum(InsightCategory), nullable=False, index=True)
    source = Column(SQLEnum(InsightSource), nullable=False)
    insight_text = Column(Text, nullable=False)
    prompt_directive = Column(Text, nullable=False)

    # Evidence
    confidence = Column(Float, default=0.5)
    sample_size = Column(Integer, default=0)
    evidence_json = Column(Text, nullable=True)

    # Lifecycle
    is_active = Column(Boolean, default=True, index=True)
    superseded_by = Column(Integer, ForeignKey("learning_insights.id"), nullable=True)
    times_used_in_prompts = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


class AnalysisRun(Base):
    """Tracks pattern analysis executions."""
    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_type = Column(String(50), nullable=False)
    posts_analyzed = Column(Integer, default=0)
    insights_created = Column(Integer, default=0)
    insights_updated = Column(Integer, default=0)
    insights_superseded = Column(Integer, default=0)
    run_duration_seconds = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# --- Autoresearch System (Karpathy-style experimentation) ---


class ExperimentType(enum.Enum):
    HOOK = "hook"
    TONE = "tone"
    TEMPLATE = "template"
    LENGTH = "length"
    ANGLE = "angle"


class Experiment(Base):
    """A single autoresearch experiment — generates N variations, picks a winner."""
    __tablename__ = "experiments"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # What was tested
    experiment_type = Column(SQLEnum(ExperimentType), nullable=False, index=True)
    topic = Column(String(200))
    hypothesis = Column(Text)
    dimension_tested = Column(String(100))  # e.g. "hook_style", "tone"

    # Results
    winner_variation_id = Column(Integer, ForeignKey("experiment_variations.id"), nullable=True)
    winner_score = Column(Integer, nullable=True)  # virality score of winner
    variations_count = Column(Integer, default=0)
    score_spread = Column(Integer, default=0)  # max - min score

    # Link to queued post (winner)
    queued_post_id = Column(Integer, ForeignKey("queued_posts.id"), nullable=True)

    # Calibration (filled later when real engagement arrives)
    actual_engagement_score = Column(Float, nullable=True)
    calibration_delta = Column(Float, nullable=True)  # predicted - actual

    created_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

    variations = relationship("ExperimentVariation", back_populates="experiment",
                              foreign_keys="ExperimentVariation.experiment_id")


class ExperimentVariation(Base):
    """One variation within an experiment."""
    __tablename__ = "experiment_variations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(Integer, ForeignKey("experiments.id"), nullable=False, index=True)

    # What was varied
    variation_label = Column(String(100))  # e.g. "question_hook", "vulnerable_tone"
    parameter_value = Column(String(200))  # the specific value tested

    # Generated content
    content = Column(Text, nullable=False)
    virality_score = Column(Integer, nullable=True)
    virality_breakdown = Column(Text, nullable=True)  # JSON

    # Post metadata
    is_winner = Column(Boolean, default=False)
    hook_type = Column(String(50))
    template_name = Column(String(100))
    tone = Column(String(50))
    word_count = Column(Integer)

    created_at = Column(DateTime, default=datetime.utcnow)

    experiment = relationship("Experiment", back_populates="variations",
                              foreign_keys=[experiment_id])
