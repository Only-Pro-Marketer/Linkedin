"""Versioned, idempotent schema migrations for SQLite.

New tables come from ``Base.metadata.create_all``. This module only adds
columns to existing tables (SQLite has no auto-migration) and backfills data.
Each step runs once; its version is recorded in ``schema_version``. Steps are
written to be safe to re-run anyway (they skip columns that already exist).
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)


def _columns(conn: Connection, table: str) -> set[str]:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _add_columns(conn: Connection, table: str, cols: dict[str, str]) -> None:
    existing = _columns(conn, table)
    if not existing:
        return  # table not created yet — create_all will build it with all columns
    for name, ddl in cols.items():
        if name not in existing:
            conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
            logger.info("Migration: added %s.%s", table, name)


def _v1_queue_workflow(conn: Connection) -> None:
    """Approval tracking, error field, quality engine and source columns."""
    _add_columns(conn, "queued_posts", {
        "approved_at": "DATETIME",
        "last_error": "TEXT",
        "attempt_count": "INTEGER DEFAULT 0",
        "source": "VARCHAR(50)",
        "first_comment": "TEXT",
        "quality_score": "INTEGER",
        "quality_report": "TEXT",
        "formula_id": "VARCHAR(20)",
        "goal": "VARCHAR(20)",
    })
    # Posts that were approved before approved_at existed keep their approval.
    conn.exec_driver_sql(
        "UPDATE queued_posts SET approved_at = updated_at "
        "WHERE approved_at IS NULL AND status IN ('APPROVED', 'SCHEDULED', 'POSTED', 'POSTING', 'FAILED')"
    )
    _add_columns(conn, "hook_library", {
        "formula_id": "VARCHAR(20)",
        "template_text": "TEXT",
    })


MIGRATIONS = [
    (1, "queue workflow + quality columns", _v1_queue_workflow),
]


def _backup(db_path: str) -> None:
    src = Path(db_path)
    if not src.exists() or src.stat().st_size == 0:
        return
    backup_dir = src.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    dest = backup_dir / f"{src.stem}-{datetime.now():%Y%m%d-%H%M%S}{src.suffix}"
    shutil.copy2(src, dest)
    logger.info("Database backed up to %s before migrating", dest)


def run_migrations(engine: Engine, db_path: str | None = None) -> list[int]:
    """Apply pending migrations. Returns the versions applied."""
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "version INTEGER PRIMARY KEY, description TEXT, applied_at DATETIME)"
        )
        done = {row[0] for row in conn.exec_driver_sql("SELECT version FROM schema_version")}

    pending = [m for m in MIGRATIONS if m[0] not in done]
    if not pending:
        return []

    if db_path and done:
        _backup(db_path)  # only back up databases that already had migrations

    applied = []
    for version, description, step in pending:
        try:
            with engine.begin() as conn:
                step(conn)
                conn.execute(
                    text("INSERT INTO schema_version (version, description, applied_at) VALUES (:v, :d, :t)"),
                    {"v": version, "d": description, "t": datetime.utcnow()},
                )
            applied.append(version)
            logger.info("Migration v%d applied: %s", version, description)
        except Exception:
            logger.exception("Migration v%d failed: %s", version, description)
            raise
    return applied
