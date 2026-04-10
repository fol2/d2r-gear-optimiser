"""Database engine and session management.

DB path is configurable via the ``D2R_DB_PATH`` environment variable.
Falls back to ``./stash.db`` in the current working directory.
"""

import os
from collections.abc import Generator

from sqlmodel import Session, SQLModel, create_engine

import d2r_optimiser.core.db.schema as _schema  # noqa: F401 — registers all tables

_DEFAULT_DB_PATH = "./stash.db"


def _db_url() -> str:
    """Build the SQLite connection URL from env or default."""
    path = os.environ.get("D2R_DB_PATH", _DEFAULT_DB_PATH)
    return f"sqlite:///{path}"


_engine = None


def get_engine(*, url: str | None = None):
    """Return (and cache) the SQLAlchemy engine.

    Pass *url* to override the default for testing (e.g. ``"sqlite://"``
    for an in-memory database).
    """
    global _engine  # noqa: PLW0603
    if _engine is None or url is not None:
        _engine = create_engine(url or _db_url(), echo=False)
    return _engine


def get_session() -> Generator[Session]:
    """Yield a SQLModel session (context-manager style)."""
    engine = get_engine()
    with Session(engine) as session:
        yield session


def create_all_tables(*, engine=None) -> None:
    """Create every table that has been registered with SQLModel.metadata."""
    engine = engine or get_engine()
    SQLModel.metadata.create_all(engine)


def reset_engine() -> None:
    """Dispose of the cached engine (useful between tests)."""
    global _engine  # noqa: PLW0603
    if _engine is not None:
        _engine.dispose()
        _engine = None
