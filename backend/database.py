"""Database engine and session factory."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

logger = logging.getLogger(__name__)

# Convert sqlite:/// to sqlite+aiosqlite:///
db_url = settings.DATABASE_URL
if db_url.startswith("sqlite:///"):
    db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)

engine = create_async_engine(db_url, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


async def init_db() -> None:
    """Create all tables (called at startup) and apply lightweight migrations."""
    from backend.models.meeting import Meeting  # noqa: F401
    from backend.models.requirement import Requirement  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
    logger.info("Database tables ensured")


async def _ensure_columns(conn) -> None:  # type: ignore[no-untyped-def]
    """Best-effort additive migration for SQLite.

    SQLAlchemy's ``create_all`` won't ALTER existing tables, so when we
    add a new column we explicitly issue ``ALTER TABLE ... ADD COLUMN``
    and ignore the "duplicate column" error if the column already exists.
    Postgres/MySQL would normally use Alembic; for our SQLite-only setup
    this stays simple and idempotent.
    """
    from sqlalchemy import text

    additions: list[tuple[str, str, str]] = [
        # (table, column, ddl_type)
        ("meetings", "kb_doc_id", "VARCHAR(64)"),
        ("meetings", "kb_url", "TEXT"),
        ("meetings", "kb_synced_at", "DATETIME"),
        # KB project association + stakeholder graph (added 2026-04-28)
        ("meetings", "kb_project_id", "VARCHAR(64)"),
        ("meetings", "kb_project_name", "VARCHAR(256)"),
        ("meetings", "stakeholder_map", "TEXT"),
        ("meetings", "stakeholder_kb_doc_id", "VARCHAR(64)"),
        ("meetings", "stakeholder_kb_url", "TEXT"),
        ("meetings", "stakeholder_kb_synced_at", "DATETIME"),
    ]
    for table, column, ddl_type in additions:
        try:
            await conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
            )
            logger.info("DB migration: added %s.%s", table, column)
        except Exception as exc:  # noqa: BLE001 — sqlite raises generic errors
            msg = str(exc).lower()
            if "duplicate column" in msg or "already exists" in msg:
                continue
            logger.warning("DB migration: skipping %s.%s (%s)", table, column, exc)


async def get_session() -> AsyncSession:  # type: ignore[misc]
    """Yield an async session for dependency injection."""
    async with async_session_factory() as session:
        yield session
