"""Database (sessions on the app's Supabase Postgres engine) and Repository (reads and all-or-nothing writes).

The engine is the one in packages/database/db.py (DATABASE_URL from .env); this module adds no second
connection pool. Importing it loads .env and raises if DATABASE_URL is unset, but does not connect.
"""

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.expression import Executable

from packages.database.db import engine as _engine


class Database:
    """Session factory on the shared engine; one instance per process."""

    def __init__(self, engine: Engine = _engine) -> None:
        self.engine: Engine = engine
        # expire_on_commit=False: objects Repository.write returns stay readable after the session closes
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def session(self) -> Session:
        """A new session on the shared engine; use it in a with block."""
        return self._sessions()


class Repository:
    """Every query and every write against the orm models goes through here."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def read(self, statement, params: dict | None = None) -> list:
        """Run a query: one selected entity/column gives models/values, several give rows."""
        with self._database.session() as session:
            result = session.execute(statement, params)
            return list(result.scalars()) if len(result.keys()) == 1 else list(result)

    def write(self, *items) -> int:
        """Add ORM objects and run insert/update/delete statements in order, all-or-nothing.
        Returns the rows the statements changed (added objects are not counted)."""
        changed = 0
        with self._database.session() as session, session.begin():
            added = []
            for item in items:
                if isinstance(item, Executable):
                    changed += max(session.execute(item).rowcount, 0)  # -1: the driver could not tell
                else:
                    session.add(item)
                    session.flush()  # without relationship()s one flush orders tables by class name, not FK
                    added.append(item)
            for obj in added:
                session.refresh(obj)  # load server defaults and trigger-written columns before close
        return changed


database = Database()  # built when the application first imports packages.db
repository = Repository(database)
