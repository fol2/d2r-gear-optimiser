"""Database helpers for CLI commands — engine init and session management."""

from sqlmodel import Session

from d2r_optimiser.core.db import create_all_tables, get_engine, reset_engine


def ensure_db(db_path: str) -> Session:
    """Initialise the database and return a new session.

    Creates all tables on first access. The caller is responsible for
    closing the returned session.
    """
    reset_engine()
    url = f"sqlite:///{db_path}"
    engine = get_engine(url=url)
    create_all_tables(engine=engine)
    return Session(engine)
