"""Steps: the unit the services log and audit.

    with audit_step("ordersUserAll", user_id=user_id) as step:
        orders = ...
        step.done(f"{len(orders)} orders")

- Both kinds log '<step> started: <inputs>' and '<step> finished in N ms: <result>' (or failed).
- audit_step also writes one row per (request ID, step name) when the step ends, in one upsert
  (packages.audit Audit.write): timestamp = when the step started, actual_log =
  '<inputs> -> <result> (N ms)', and on failure error_log = '<Error>: <message>'.
  The step name must be in a stepNameList in packages/audit/audit.json, which picks the table
  (orders_audit, review_audit or home_audit).
- log_step only logs (for endpoint groups without an audit table: cart, account).

Audit rows are written through their own small connection pool, so they never wait on (or hold)
the connections the requests use. With audit.background=true (app.properties) one worker thread
writes them in order and requests do not wait for Supabase; its queue is bounded
(audit.max_pending): when it is full, rows are dropped with a warning instead of piling up.
"""

import contextvars
import json
import logging
import queue
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.errors import InvalidInputError, NotFoundError
from app.request_id import get_request_id
from packages.audit import Audit
from packages.database.db import DATABASE_URL

logger = logging.getLogger(__name__)

# Step lines name the service that ran the step (this generator <- contextlib <- service).
_CALLER = 3


class AuditWriter:
    """Runs audit writes (which never raise), inline or on one background worker thread.

    In background mode the worker runs them in submission order. Each runs in a copy of the
    submitting request's context, so anything the audit package logs still carries that request's
    ID. The queue holds at most max_pending writes; beyond that a write is dropped and logged.
    """

    def __init__(self, enabled: bool, background: bool, max_pending: int = 10_000) -> None:
        self.enabled = enabled
        self.background = background
        self.max_pending = max_pending
        self.dropped = 0
        self._queue: queue.Queue = queue.Queue(maxsize=max_pending)
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    def submit(self, call: Callable, *args, **kwargs) -> None:
        if not self.enabled:
            return
        if not self.background:
            call(*args, **kwargs)
            return
        self._start_worker()
        try:
            self._queue.put_nowait((contextvars.copy_context(), call, args, kwargs))
        except queue.Full:
            with self._lock:
                self.dropped += 1
                dropped = self.dropped
            logger.warning("Audit queue full (%d writes waiting): one audit row dropped, %d so far",
                           self.max_pending, dropped)

    def pending(self) -> int:
        """Writes queued or in progress."""
        return self._queue.unfinished_tasks

    def flush(self, timeout: float | None = None) -> bool:
        """Wait until every queued write is done. False if timeout seconds passed first."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
        return True

    def _start_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._work, name="audit-writer", daemon=True)
                self._worker.start()

    def _work(self) -> None:
        while True:
            context, call, args, kwargs = self._queue.get()
            try:
                context.run(call, *args, **kwargs)
            except Exception:  # Audit.write never raises; this only guards the worker itself
                logger.exception("Audit write raised")
            finally:
                self._queue.task_done()


def _audit_sessions() -> sessionmaker:
    """Sessions on a small pool of their own (no connection is opened until the first write)."""
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=4,
        pool_timeout=5,
        connect_args={"connect_timeout": 5},
    )
    return sessionmaker(engine)


_settings = get_settings()
audit_store = Audit(session_factory=_audit_sessions())
audit_writer = AuditWriter(enabled=_settings.audit_enabled, background=_settings.audit_background,
                           max_pending=_settings.audit_max_pending)


class Step:
    def __init__(self, inputs: str) -> None:
        self.inputs = inputs
        self.result: str | None = None

    def done(self, result: str) -> None:
        """The step's outcome, written to the log line and the audit row's actual_log."""
        self.result = result


def _as_text(inputs: dict) -> str:
    return json.dumps(inputs, default=str)


@contextmanager
def _step(step_name: str, audited: bool, inputs: dict) -> Iterator[Step]:
    step = Step(_as_text(inputs))
    request_id = get_request_id() if audited else None
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    logger.info("%s started: %s", step_name, step.inputs, stacklevel=_CALLER)
    try:
        yield step
    except Exception as exc:
        ms = round((time.perf_counter() - started) * 1000)
        error = f"{type(exc).__name__}: {exc}"
        level = logging.WARNING if isinstance(exc, (NotFoundError, InvalidInputError)) else logging.ERROR
        logger.log(level, "%s failed after %d ms: %s", step_name, ms, error, stacklevel=_CALLER)
        if request_id:
            audit_writer.submit(audit_store.write, request_id, step_name,
                                log_col=f"{step.inputs} -> failed ({ms} ms)", error_column=error,
                                timestamp=started_at)
        raise
    ms = round((time.perf_counter() - started) * 1000)
    result = step.result or "done"
    logger.info("%s finished in %d ms: %s", step_name, ms, result, stacklevel=_CALLER)
    if request_id:
        audit_writer.submit(audit_store.write, request_id, step_name,
                            log_col=f"{step.inputs} -> {result} ({ms} ms)", timestamp=started_at)


def audit_step(step_name: str, **inputs) -> AbstractContextManager[Step]:
    """Log and audit one step (see the module docstring)."""
    return _step(step_name, True, inputs)


def log_step(step_name: str, **inputs) -> AbstractContextManager[Step]:
    """Log one step without an audit row."""
    return _step(step_name, False, inputs)
