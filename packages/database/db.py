"""Database connection: one engine for the whole app, plus helpers to run queries."""

import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# mangla_backend/.env  (packages/database/db.py -> parents[2] is the backend root)
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Add it to mangla_backend/.env")

# The single engine (connection pool) used everywhere.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine)


@contextmanager
def get_session():
    """ORM session that commits on success and rolls back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_query(sql, params=None):
    """Run raw SQL in a transaction.

    Returns a list of dict rows for queries that return rows (e.g. SELECT),
    otherwise the number of affected rows.
    """
    with engine.begin() as conn:
        result = conn.execute(text(sql), params or {})
        if result.returns_rows:
            return [dict(row) for row in result.mappings()]
        return result.rowcount
