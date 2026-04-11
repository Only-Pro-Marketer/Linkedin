"""Database connection and initialization."""

import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from database.models import Base
from config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite needs this for FastAPI
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_research_columns():
    """Add region and category columns to research_items if missing (SQLite)."""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(research_items)")
        columns = {row[1] for row in cursor.fetchall()}
        if not columns:
            # Table doesn't exist yet — create_all will handle it
            conn.close()
            return
        if "region" not in columns:
            cursor.execute("ALTER TABLE research_items ADD COLUMN region VARCHAR(50)")
        if "category" not in columns:
            cursor.execute("ALTER TABLE research_items ADD COLUMN category VARCHAR(100)")
        conn.commit()
        conn.close()
    except Exception:
        pass  # Table will be created fresh by create_all


def _migrate_video_columns():
    """Add video/GIF columns to queued_posts and research_items if missing (SQLite)."""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Migrate queued_posts
        cursor.execute("PRAGMA table_info(queued_posts)")
        columns = {row[1] for row in cursor.fetchall()}
        if columns:  # Table exists
            new_cols = {
                "media_type": "VARCHAR(20) DEFAULT 'none'",
                "video_path": "VARCHAR(500)",
                "video_prompt": "TEXT",
                "has_video": "BOOLEAN DEFAULT 0",
                "video_duration": "INTEGER",
                "video_source": "VARCHAR(50)",
            }
            for col, col_type in new_cols.items():
                if col not in columns:
                    cursor.execute(f"ALTER TABLE queued_posts ADD COLUMN {col} {col_type}")

        # Migrate research_items
        cursor.execute("PRAGMA table_info(research_items)")
        columns = {row[1] for row in cursor.fetchall()}
        if columns:
            if "screenshot_path" not in columns:
                cursor.execute("ALTER TABLE research_items ADD COLUMN screenshot_path VARCHAR(500)")
            if "data_points" not in columns:
                cursor.execute("ALTER TABLE research_items ADD COLUMN data_points TEXT")

        conn.commit()
        conn.close()
    except Exception:
        pass


def _migrate_learning_columns():
    """Add learning system columns to queued_posts if missing (SQLite)."""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(queued_posts)")
        columns = {row[1] for row in cursor.fetchall()}
        if columns and "rejection_categories" not in columns:
            cursor.execute("ALTER TABLE queued_posts ADD COLUMN rejection_categories TEXT")
        conn.commit()
        conn.close()
    except Exception:
        pass


def _migrate_research_hub_columns():
    """Add notes, velocity, and performance columns for research hub improvements."""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Research items: notes + velocity columns
        cursor.execute("PRAGMA table_info(research_items)")
        ri_cols = {row[1] for row in cursor.fetchall()}
        if ri_cols:
            new_ri_cols = {
                "notes": "TEXT",
                "first_seen_at": "DATETIME",
                "appearance_count": "INTEGER DEFAULT 1",
                "normalized_topic_key": "VARCHAR(200)",
                "velocity": "VARCHAR(20)",
            }
            for col, col_type in new_ri_cols.items():
                if col not in ri_cols:
                    cursor.execute(f"ALTER TABLE research_items ADD COLUMN {col} {col_type}")

        # Queued posts: research_item_id FK
        cursor.execute("PRAGMA table_info(queued_posts)")
        qp_cols = {row[1] for row in cursor.fetchall()}
        if qp_cols and "research_item_id" not in qp_cols:
            cursor.execute(
                "ALTER TABLE queued_posts ADD COLUMN research_item_id INTEGER REFERENCES research_items(id)"
            )

        conn.commit()
        conn.close()
    except Exception:
        pass


def _migrate_autoresearch_tables():
    """Create experiments and experiment_variations tables if missing (SQLite)."""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # Check if experiments table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='experiments'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE experiments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_type VARCHAR(20) NOT NULL,
                    topic VARCHAR(200),
                    hypothesis TEXT,
                    dimension_tested VARCHAR(100),
                    winner_variation_id INTEGER,
                    winner_score INTEGER,
                    variations_count INTEGER DEFAULT 0,
                    score_spread INTEGER DEFAULT 0,
                    queued_post_id INTEGER REFERENCES queued_posts(id),
                    actual_engagement_score REAL,
                    calibration_delta REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT
                )
            """)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='experiment_variations'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE experiment_variations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id INTEGER NOT NULL REFERENCES experiments(id),
                    variation_label VARCHAR(100),
                    parameter_value VARCHAR(200),
                    content TEXT NOT NULL,
                    virality_score INTEGER,
                    virality_breakdown TEXT,
                    is_winner BOOLEAN DEFAULT 0,
                    hook_type VARCHAR(50),
                    template_name VARCHAR(100),
                    tone VARCHAR(50),
                    word_count INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
        conn.commit()
        conn.close()
    except Exception:
        pass


def _migrate_commenting_columns():
    """Add commenting columns to competitor_posts if missing."""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(competitor_posts)")
        columns = {row[1] for row in cursor.fetchall()}
        if columns:
            if "commented_at" not in columns:
                cursor.execute("ALTER TABLE competitor_posts ADD COLUMN commented_at DATETIME")
            if "comment_draft" not in columns:
                cursor.execute("ALTER TABLE competitor_posts ADD COLUMN comment_draft TEXT")
        conn.commit()
        conn.close()
    except Exception:
        pass


def _migrate_recycled_column():
    """Add recycled_from_id column to queued_posts if missing."""
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(queued_posts)")
        columns = {row[1] for row in cursor.fetchall()}
        if columns and "recycled_from_id" not in columns:
            cursor.execute("ALTER TABLE queued_posts ADD COLUMN recycled_from_id INTEGER")
        conn.commit()
        conn.close()
    except Exception:
        pass


def _seed_content_calendar():
    """Populate default posting time slots if the content_calendar table is empty.

    Optimal posting times based on engagement data:
    - Tue/Wed/Thu 08:30 (primary — 200+ avg engagement before 10am)
    - Mon/Fri 09:00 (secondary)
    - No weekends (2-3 avg engagement)
    """
    from database.models import ContentCalendar

    db = SessionLocal()
    try:
        if db.query(ContentCalendar).count() > 0:
            return

        default_slots = [
            # Primary slots: Tue(1), Wed(2), Thu(3) at 08:30
            ContentCalendar(day_of_week=1, time_slot="08:30", is_active=True),
            ContentCalendar(day_of_week=2, time_slot="08:30", is_active=True),
            ContentCalendar(day_of_week=3, time_slot="08:30", is_active=True),
            # Secondary slots: Mon(0), Fri(4) at 09:00
            ContentCalendar(day_of_week=0, time_slot="09:00", is_active=True),
            ContentCalendar(day_of_week=4, time_slot="09:00", is_active=True),
        ]
        db.add_all(default_slots)
        db.commit()
    finally:
        db.close()


def init_database():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    _migrate_research_columns()
    _migrate_video_columns()
    _migrate_learning_columns()
    _migrate_research_hub_columns()
    _migrate_autoresearch_tables()
    _migrate_recycled_column()
    _migrate_commenting_columns()
    _seed_content_calendar()


def get_db() -> Session:
    """Dependency for FastAPI routes — yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
