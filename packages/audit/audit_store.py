"""Write request audits: record a step's row, update its logs, and keep each table under its rollingSize.

Every audit table has the 5 columns of sql/NOIDraftEntryAudit.sql, keyed by (RequestID, StepName).
The caller's code supplies the request ID and the step name (a unique name for one process); the step
name picks the table (audit.json, see audit_config.py). Nothing here raises into the caller:
a config or database problem is logged and the function returns False (0 for enforce_rolling_size),
and even a failing log handler (e.g. a log file that cannot be written) is ignored.
If the database is unreachable a call can still wait for the connection timeout (about 60 s, 15 s for
db.target local, plus up to 60 s for the `az login` token; see packages/db.py).
"""

import contextlib
import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mssql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from packages.audit.audit_config import (
    STEP_NAME_MAX_LENGTH,
    AuditConfig,
    AuditConfigError,
    TableSettings,
    load_audit_config,
)
from packages.common_logger.log_masker import masker

logger = logging.getLogger(__name__)

_LONG_TEXT = sa.UnicodeText().with_variant(mssql.NVARCHAR(), "mssql")  # nvarchar(max), never ntext


def build_audit_table(settings: TableSettings, metadata: sa.MetaData) -> sa.Table:
    """The Core table for one audit table (the columns of sql/NOIDraftEntryAudit.sql)."""
    return sa.Table(
        settings.name,
        metadata,
        sa.Column("RequestID", sa.Uuid(), nullable=False),
        sa.Column("Timestamp", sa.DateTime().with_variant(mssql.DATETIME2(6), "mssql"), nullable=False),
        sa.Column("StepName", sa.Unicode(STEP_NAME_MAX_LENGTH), nullable=False),
        sa.Column("ActualLog", _LONG_TEXT),
        sa.Column("ErrorLog", _LONG_TEXT),
        sa.PrimaryKeyConstraint("RequestID", "StepName", name=f"PK_{settings.name}"),
        schema=settings.schema,
        implicit_returning=False,
    )


def build_audit_insert(table: sa.Table, request_id: uuid.UUID, step_name: str, timestamp: datetime,
                       log: str | None) -> sa.Insert:
    """The INSERT for one step's row; ErrorLog starts empty (NULL)."""
    return sa.insert(table).values(RequestID=request_id, Timestamp=timestamp, StepName=step_name,
                                   ActualLog=log, ErrorLog=None)


def build_audit_update(table: sa.Table, request_id: uuid.UUID, step_name: str, values: dict) -> sa.Update:
    """The UPDATE that overwrites the given log columns of one step's row."""
    return (
        sa.update(table)
        .where(table.c.RequestID == request_id, table.c.StepName == step_name)
        .values(values)
    )


def build_audit_trim(table: sa.Table, rolling_size: int, keep_request: uuid.UUID | None = None) -> sa.Delete:
    """The DELETE of every row of the oldest requests that do not fit in rolling_size rows.

    Requests are ranked newest first by their first Timestamp; a request is deleted, all of its
    rows, once the running total of rows up to and including it passes rolling_size. keep_request is
    never deleted. One statement with no list of IDs (SQL Server allows 2,100 parameters) and no
    row-value IN (SQL Server has none).
    """
    source = table.alias("audit_source")
    requests = (
        sa.select(source.c.RequestID, sa.func.min(source.c.Timestamp).label("first_seen"),
                  sa.func.count().label("request_rows"))
        .group_by(source.c.RequestID)
        .subquery("requests")
    )
    kept_rows = sa.func.sum(requests.c.request_rows).over(
        order_by=(requests.c.first_seen.desc(), requests.c.RequestID.desc()), rows=(None, 0),
    )
    ranked = sa.select(requests.c.RequestID, kept_rows.label("kept_rows")).subquery("ranked")
    oldest = sa.select(ranked.c.RequestID).where(ranked.c.kept_rows > rolling_size)
    if keep_request is not None:
        oldest = oldest.where(ranked.c.RequestID != keep_request)
    return sa.delete(table).where(table.c.RequestID.in_(oldest))


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
            session_factory: returns a new Session, or None for packages.db's database.session.
            clock: returns the Timestamp to write (naive UTC), or None for the current UTC time.
        """
        self._config = config
        self._session_factory = session_factory
        self._clock = clock or _utc_now
        self.metadata = sa.MetaData()
        self._tables: dict[str, sa.Table] = {}
        self._lock = threading.Lock()  # requests may audit from several threads at once

    def record(self, request_id, step_name: str, log_col=None) -> bool:
        """Insert this step's row (Timestamp = now, ErrorLog empty), then trim the table to its rollingSize.

        Call it at the start of the caller's try block.

        Args:
            request_id: the caller's request ID, a UUID (uuid.UUID or its text).
            step_name: the caller's name for this process; audit.json maps it to the table.
            log_col: the ActualLog text (None = NULL).

        Returns:
            True if the row was written; False if not (unknown step, auditflag false, the row already
            exists, or a config/database problem, which is logged).
        """
        try:
            return self._record(request_id, step_name, log_col)
        except Exception as exc:  # an audit problem must never reach the request
            _log_failure("record", step_name, exc)
            return False

    def update(self, request_id, step_name: str, error_column=None, log_col=None) -> bool:
        """Overwrite ErrorLog (error_column) and/or ActualLog (log_col) of the row record() wrote.

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
                    table = self._tables[table_name] = build_audit_table(settings, self.metadata)
        return table

    def _record(self, request_id, step_name, log_col) -> bool:
        target = self._target("record", step_name, request_id)
        if target is None:
            return False
        settings, request = target
        table = self.table(settings.name)
        statement = build_audit_insert(table, request, step_name, self._clock(), _masked(log_col))
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

    def _update(self, request_id, step_name, error_column, log_col) -> bool:
        values = {column: _masked(text)
                  for column, text in (("ErrorLog", error_column), ("ActualLog", log_col))
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
        """A new session: the given factory, else packages.db's.

        packages.db is imported here, on the first call, so importing this module never connects.
        """
        if self._session_factory is None:
            from packages.db import database  # loads .env and picks the database by db.target

            self._session_factory = database.session
        return self._session_factory()


def _utc_now() -> datetime:
    """The current UTC time without tzinfo (DATETIME2 holds no offset; the column is UTC by convention)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _request_uuid(value) -> uuid.UUID | None:
    """value as a UUID (a uuid.UUID or its text), or None when it is not one."""
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _masked(text) -> str | None:
    """Log text masked like the log files (session tokens always, ER numbers per mask_sensitive_data).

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
    reach the request; RolloverFileHandler.emit does not call handleError, so its errors propagate."""
    with contextlib.suppress(Exception):
        logger.log(level, message, *args)


def _log_failure(action: str, name, exc: Exception) -> None:
    """Log why an audit call wrote nothing: a bad audit.json as an error, anything else as a warning."""
    if isinstance(exc, AuditConfigError):
        _log(logging.ERROR, "Audit %s skipped (%r): %s", action, name, exc)
    else:
        _log(logging.WARNING, "Audit %s failed (%r): %s", action, name, _describe(exc))


audit = Audit()  # the shared instance: audit.json and packages.db, both loaded on its first call
