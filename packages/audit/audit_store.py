"""Write request audits: record a step's row, update its logs, and keep each table under its rollingSize.

Every audit table has the same 5 columns (build_audit_table below), keyed by (request_id, step_name),
in Supabase Postgres. The caller's code supplies the request ID and the step name (a unique name for
one process); the step name picks the table (audit.json, see audit_config.py). Nothing here raises
into the caller: a config or database problem is logged and the function returns False (0 for
enforce_rolling_size), and even a failing log handler (e.g. a log file that cannot be written) is
ignored. The writes go through the app's one engine (packages/database/db.py, DATABASE_URL in .env);
if Supabase is unreachable a call still waits for the connection attempt to fail.
"""

import contextlib
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.audit.audit_config import (
    DEFAULT_SCHEMA,
    AuditConfig,
    AuditConfigError,
    TableSettings,
    load_audit_config,
)
from packages.common_logger.log_masker import masker

logger = logging.getLogger(__name__)

TRIM_EVERY_WRITES = 100  # write() checks rollingSize on a table's 1st, 101st, 201st ... write


def build_audit_table(name: str, metadata: sa.MetaData, schema: str = DEFAULT_SCHEMA) -> sa.Table:
    """The Core table for one audit table; scripts/create_audit_tables.py creates it from this too."""
    return sa.Table(
        name,
        metadata,
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("timestamp", postgresql.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("step_name", sa.Text(), nullable=False),
        sa.Column("actual_log", sa.Text()),
        sa.Column("error_log", sa.Text()),
        sa.PrimaryKeyConstraint("request_id", "step_name", name=f"{name}_pkey"),
        schema=schema,
    )


def build_audit_insert(table: sa.Table, request_id: uuid.UUID, step_name: str, log: str | None,
                       timestamp: datetime | None = None) -> sa.Insert:
    """The INSERT for one step's row; error_log starts empty (NULL), timestamp None = the database's now()."""
    values = {"request_id": request_id, "step_name": step_name, "actual_log": log, "error_log": None}
    if timestamp is not None:
        values["timestamp"] = timestamp
    return sa.insert(table).values(values)


def build_audit_update(table: sa.Table, request_id: uuid.UUID, step_name: str, values: dict) -> sa.Update:
    """The UPDATE that overwrites the given log columns of one step's row."""
    return (
        sa.update(table)
        .where(table.c.request_id == request_id, table.c.step_name == step_name)
        .values(values)
    )


def build_audit_trim(table: sa.Table, rolling_size: int, keep_request: uuid.UUID | None = None) -> sa.Delete:
    """The DELETE of every row of the oldest requests that do not fit in rolling_size rows.

    Requests are ranked newest first by their first timestamp; a request is deleted, all of its
    rows, once the running total of rows up to and including it passes rolling_size. keep_request is
    never deleted. One statement, with no list of IDs sent from Python.
    """
    source = table.alias("audit_source")
    requests = (
        sa.select(source.c.request_id, sa.func.min(source.c.timestamp).label("first_seen"),
                  sa.func.count().label("request_rows"))
        .group_by(source.c.request_id)
        .subquery("requests")
    )
    kept_rows = sa.func.sum(requests.c.request_rows).over(
        order_by=(requests.c.first_seen.desc(), requests.c.request_id.desc()), rows=(None, 0),
    )
    ranked = sa.select(requests.c.request_id, kept_rows.label("kept_rows")).subquery("ranked")
    oldest = sa.select(ranked.c.request_id).where(ranked.c.kept_rows > rolling_size)
    if keep_request is not None:
        oldest = oldest.where(ranked.c.request_id != keep_request)
    return sa.delete(table).where(table.c.request_id.in_(oldest))


class Audit:
    """Audit writes for the tables in audit.json; `audit` below is the shared instance callers use."""

    def __init__(
        self,
        config: AuditConfig | None = None,
        session_factory: Callable[[], Session] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Keep what the writes need; nothing is loaded or connected until the first call.

        Args:
            config: the audit config, or None to load audit.json on first use.
            session_factory: returns a new Session, or None for packages.database's SessionLocal.
            clock: returns the timestamp to write (timezone-aware), or None to let the database
                fill it (now(), the time the insert's transaction started).
        """
        self._config = config
        self._session_factory = session_factory
        self._clock = clock
        self.metadata = sa.MetaData()
        self._tables: dict[str, sa.Table] = {}
        self._writes: dict[str, int] = {}  # write() calls per table, for the periodic trim
        self._lock = threading.Lock()  # requests may audit from several threads at once

    def record(self, request_id, step_name: str, log_col=None) -> bool:
        """Insert this step's row (timestamp = now, error_log empty), then trim the table to its rollingSize.

        Call it at the start of the caller's try block.

        Args:
            request_id: the caller's request ID, a UUID (uuid.UUID or its text).
            step_name: the caller's name for this process; audit.json maps it to the table.
            log_col: the actual_log text (None = NULL).

        Returns:
            True if the row was written; False if not (unknown step, auditflag false, the row already
            exists, or a config/database problem, which is logged).
        """
        try:
            return self._record(request_id, step_name, log_col)
        except Exception as exc:  # an audit problem must never reach the request
            _log_failure("record", step_name, exc)
            return False

    def write(self, request_id, step_name: str, log_col=None, error_column=None,
              timestamp: datetime | None = None) -> bool:
        """Write a finished step's whole row in ONE transaction (an upsert), instead of record + update.

        Inserts the row, or, when this (request ID, step name) row already exists, overwrites its
        actual_log and error_log. The table is trimmed to its rollingSize every TRIM_EVERY_WRITES
        writes (and on the first write) rather than after every row, so a write costs one round of
        Supabase trips; between trims a table can exceed rollingSize by fewer than that many rows.

        Args:
            request_id: the caller's request ID, a UUID (uuid.UUID or its text).
            step_name: the caller's name for this process; audit.json maps it to the table.
            log_col: the actual_log text (None = NULL).
            error_column: the error_log text (None = NULL).
            timestamp: when the step happened (timezone-aware), or None for the database's now().

        Returns:
            True if the row was written; False if not (unknown step, auditflag false, or a
            config/database problem, which is logged).
        """
        try:
            return self._write(request_id, step_name, log_col, error_column, timestamp)
        except Exception as exc:
            _log_failure("write", step_name, exc)
            return False

    def update(self, request_id, step_name: str, error_column=None, log_col=None) -> bool:
        """Overwrite error_log (error_column) and/or actual_log (log_col) of the row record() wrote.

        Call it at the end of the try block with log_col, and in the except block with error_column.
        A column left out (None) keeps its value, so an error update keeps the recorded log.

        Returns:
            True if the row was updated; False if not (nothing given, unknown step, auditflag false,
            no such row, or a config/database problem, which is logged).
        """
        try:
            return self._update(request_id, step_name, error_column, log_col)
        except Exception as exc:
            _log_failure("update", step_name, exc)
            return False

    def enforce_rolling_size(self, table_name: str, keep_request=None) -> int:
        """When the table holds more than its rollingSize rows, delete its oldest whole requests.

        Args:
            table_name: a table from audit.json.
            keep_request: a request ID that is never deleted (the one being audited), or None.

        Returns:
            The number of rows deleted (0 when under the limit or on a problem, which is logged).
        """
        try:
            return self._enforce_rolling_size(table_name, keep_request)
        except Exception as exc:
            _log_failure("rolling-size trim", table_name, exc)
            return 0

    def table(self, table_name: str) -> sa.Table:
        """The Core table for a table in audit.json (built once per store).

        Raises:
            AuditConfigError: if audit.json is bad.
            KeyError: if the table is not in audit.json.
        """
        table = self._tables.get(table_name)
        if table is None:
            with self._lock:  # a second build on the same MetaData would raise "already defined"
                table = self._tables.get(table_name)
                if table is None:
                    settings = self._get_config().tables[table_name]
                    table = self._tables[table_name] = build_audit_table(
                        settings.name, self.metadata, settings.schema)
        return table

    def _record(self, request_id, step_name, log_col) -> bool:
        target = self._target("record", step_name, request_id)
        if target is None:
            return False
        settings, request = target
        table = self.table(settings.name)
        timestamp = self._clock() if self._clock else None
        statement = build_audit_insert(table, request, step_name, _masked(log_col), timestamp)
        try:
            with self._session() as session, session.begin():
                session.execute(statement)
        except IntegrityError as exc:
            _log(logging.WARNING, "Audit record skipped: %s.%s refused the %s row of request %s "
                 "(already recorded?): %s", settings.schema, settings.name, step_name, request,
                 _describe(exc))
            return False
        # after the commit: a failed trim keeps the row
        self.enforce_rolling_size(settings.name, keep_request=request)
        return True

    def _write(self, request_id, step_name, log_col, error_column, timestamp) -> bool:
        target = self._target("write", step_name, request_id)
        if target is None:
            return False
        settings, request = target
        table = self.table(settings.name)
        values = {"request_id": request, "step_name": step_name,
                  "actual_log": _masked(log_col), "error_log": _masked(error_column)}
        stamp = timestamp or (self._clock() if self._clock else None)
        if stamp is not None:
            values["timestamp"] = stamp
        insert = postgresql.insert(table).values(values)
        statement = insert.on_conflict_do_update(
            index_elements=[table.c.request_id, table.c.step_name],
            set_={"actual_log": insert.excluded.actual_log, "error_log": insert.excluded.error_log},
        )
        with self._session() as session, session.begin():
            session.execute(statement)
        if self._trim_due(settings.name):
            self.enforce_rolling_size(settings.name, keep_request=request)  # after the commit
        return True

    def _trim_due(self, table_name: str) -> bool:
        """True on a table's first write in this process and then every TRIM_EVERY_WRITES writes."""
        with self._lock:
            count = self._writes.get(table_name, 0)
            self._writes[table_name] = count + 1
        return count % TRIM_EVERY_WRITES == 0

    def _update(self, request_id, step_name, error_column, log_col) -> bool:
        values = {column: _masked(text)
                  for column, text in (("error_log", error_column), ("actual_log", log_col))
                  if text is not None}
        if not values:
            _log(logging.WARNING, "Audit update skipped: no error_column or log_col given for step %r",
                 step_name)
            return False
        target = self._target("update", step_name, request_id)
        if target is None:
            return False
        settings, request = target
        statement = build_audit_update(self.table(settings.name), request, step_name, values)
        with self._session() as session, session.begin():
            count = session.execute(statement).rowcount
        if count != 1:
            _log(logging.WARNING, "Audit update: %s.%s has no %s row for request %s", settings.schema,
                 settings.name, step_name, request)
            return False
        return True

    def _enforce_rolling_size(self, table_name, keep_request) -> int:
        settings = self._get_config().tables.get(table_name)
        if settings is None:
            _log(logging.WARNING, "Audit rolling-size trim skipped: %r is not a table in audit.json",
                 table_name)
            return 0
        table = self.table(table_name)
        keep = None if keep_request is None else _request_uuid(keep_request)
        with self._session() as session, session.begin():
            count = session.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
            if count <= settings.rolling_size:
                return 0
            deleted = session.execute(build_audit_trim(table, settings.rolling_size, keep)).rowcount
        _log(logging.INFO, "Audit table %s.%s held %d rows (rollingSize %d): "
             "deleted %d rows of the oldest requests",
             settings.schema, table_name, count, settings.rolling_size, deleted)
        return deleted

    def _target(self, action: str, step_name, request_id) -> tuple[TableSettings, uuid.UUID] | None:
        """(the step's table, the request UUID), or None (logged) when nothing should be written."""
        settings = self._get_config().table_for(step_name)
        if settings is None:
            _log(logging.WARNING,
                 "Audit %s skipped: step %r is in no stepNameList in audit.json (add it there)",
                 action, step_name)
            return None
        if not settings.audit_flag:
            _log(logging.DEBUG, "Audit %s skipped: auditflag is false for %s (step %r)", action,
                 settings.name, step_name)
            return None
        request = _request_uuid(request_id)
        if request is None:
            _log(logging.WARNING, "Audit %s skipped: request ID %r is not a UUID (step %r)", action,
                 request_id, step_name)
            return None
        return settings, request

    def _get_config(self) -> AuditConfig:
        """The config given to the store, else audit.json (raises AuditConfigError when bad)."""
        if self._config is None:
            self._config = load_audit_config()
        return self._config

    def _session(self) -> Session:
        """A new session: the given factory, else packages.database's SessionLocal.

        packages.database is imported here, on the first call, so importing this module never needs
        DATABASE_URL or connects.
        """
        if self._session_factory is None:
            from packages.database.db import SessionLocal  # loads .env; raises if DATABASE_URL is unset

            self._session_factory = SessionLocal
        return self._session_factory()


def _request_uuid(value) -> uuid.UUID | None:
    """value as a UUID (a uuid.UUID or its text), or None when it is not one."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _masked(text) -> str | None:
    """Log text masked like the log files (secrets always, PII per mask_sensitive_data).

    None stays None (NULL).
    """
    return None if text is None else masker.mask(str(text))


def _describe(exc: Exception) -> str:
    """A short, masked reason; a database error's driver message without the SQL and its parameters."""
    reason = getattr(exc, "orig", None) or exc
    try:
        return f"{type(reason).__name__}: {masker.mask(str(reason))[:300]}"
    except Exception:  # an exception whose str() fails
        return type(reason).__name__


def _log(level: int, message: str, *args) -> None:
    """logger.log that never raises: a failing handler (e.g. a log file that cannot be written) must not
    reach the request."""
    with contextlib.suppress(Exception):
        logger.log(level, message, *args)


def _log_failure(action: str, name, exc: Exception) -> None:
    """Log why an audit call wrote nothing: a bad audit.json as an error, anything else as a warning."""
    if isinstance(exc, AuditConfigError):
        _log(logging.ERROR, "Audit %s skipped (%r): %s", action, name, exc)
    else:
        _log(logging.WARNING, "Audit %s failed (%r): %s", action, name, _describe(exc))


audit = Audit()  # the shared instance: audit.json and packages.database, both loaded on its first call
