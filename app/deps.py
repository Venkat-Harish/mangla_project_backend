"""FastAPI dependencies."""

from collections.abc import Iterator

from sqlalchemy.orm import Session

from packages.database import SessionLocal


def get_db() -> Iterator[Session]:
    """A database session for one request.

    Services that write call session.commit() themselves, before the response is built, so a
    failed commit becomes an error response instead of happening after the client got a 200.
    Anything left uncommitted (reads, or a request that failed) is rolled back here.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
