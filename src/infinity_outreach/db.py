"""Database engine and session management (SQLAlchemy 2.x)."""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings, ensure_runtime_dirs

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None
_db_ready: bool = False


def get_engine() -> Engine:
    """Lazily create the process-wide engine."""
    global _engine
    if _engine is None:
        ensure_runtime_dirs()
        settings = get_settings()
        connect_args = {}
        if settings.database_url.startswith("sqlite"):
            # Allow use across the FastAPI threadpool.
            connect_args = {"check_same_thread": False}
        _engine = create_engine(
            settings.database_url,
            echo=False,
            future=True,
            connect_args=connect_args,
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False, future=True
        )
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session context manager.

    Commits on success, rolls back on exception, always closes. The schema is
    created + migrated automatically on first use, so every entry point (CLI,
    web, autonomous loop) works against a fresh or an older database without
    anyone having to remember to run ``init-db`` first.
    """
    _ensure_ready()
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _migrate(engine) -> None:
    """Add columns introduced after initial schema. Safe to run on every boot."""
    from sqlalchemy import text

    new_columns = [
        "ALTER TABLE cities ADD COLUMN osm_searched BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE cities ADD COLUMN google_searched BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE campaign_settings ADD COLUMN regions JSON",
    ]
    with engine.connect() as conn:
        for stmt in new_columns:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # column already exists


def _ensure_ready() -> None:
    """Run the one-time schema create + migrate for this process (idempotent)."""
    global _db_ready
    if not _db_ready:
        init_db()


def init_db() -> None:
    """Create all tables and apply forward migrations. Safe to run repeatedly."""
    global _db_ready
    from .models import Base  # imported here to avoid a circular import

    ensure_runtime_dirs()
    engine = get_engine()
    Base.metadata.create_all(engine)
    _migrate(engine)
    _db_ready = True
