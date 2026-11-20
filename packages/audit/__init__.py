"""Request audits: one row per (request ID, step name) in the Supabase audit tables named in audit.json.

The calling code owns the request ID (a UUID, e.g. app.request_id.get_request_id()) and the step
name (a unique name for one process); this package only records the step and updates its logs:

    from packages.audit import audit

    def place_order(request_id):
        step_name = "orderPlace"  # must be listed in a stepNameList in audit.json
        try:
            audit.record(request_id, step_name, "empty log")
            ...  # the process
            audit.update(request_id, step_name, log_col="process log here")
        except Exception as exc:
            audit.update(request_id, step_name, error_column=f"{type(exc).__name__}: {exc}")
            raise

- audit.json maps each table (orders_audit, review_audit, home_audit, posts_audit) to its stepNameList,
  auditflag and rollingSize; the step name alone picks the table (audit_config.py). A step whose
  table has auditflag false writes nothing, and a step listed in no table logs a warning and writes
  nothing.
- record() inserts the row (timestamp = the database's now()), then trims the table to its
  rollingSize by deleting the oldest whole requests (never the current one). update() overwrites
  error_log (error_column) and/or actual_log (log_col) of that row; a column left out keeps its value.
  Both run synchronously, a few round trips to Supabase per call.
- write() is the one-call alternative for a step that has already finished: one upsert transaction
  with the final actual_log / error_log and the step's own timestamp, and a rollingSize trim only
  every TRIM_EVERY_WRITES writes. The API (app/steps.py) audits every step this way, from a
  background thread, with its own small connection pool.
- Nothing raises: a config or database problem is logged and the call returns False (0 for
  enforce_rolling_size), so auditing cannot break the process or hide its exception. Call
  load_audit_config() at start-up to fail fast on a bad audit.json.
- The database is the app's one engine (packages/database/db.py, DATABASE_URL in .env), imported on
  the first call: importing this package never connects. The tables are created by
  `python -m scripts.create_audit_tables` and documented in DATABASE.md.
"""

from packages.audit.audit_config import AuditConfig, AuditConfigError, TableSettings, load_audit_config
from packages.audit.audit_store import Audit, audit

__all__ = [
    "Audit",
    "AuditConfig",
    "AuditConfigError",
    "TableSettings",
    "audit",
    "load_audit_config",
]
