"""Request audits: one row per (request ID, step name) in the audit tables named in audit.json.

The calling code owns the request ID (a UUID) and the step name (a unique name for one process); this
package only records the step and updates its logs:

    from packages.audit import audit

    def sample_func(request_id):
        step_name = "draftCreate"  # must be listed in a stepNameList in audit.json
        try:
            audit.record(request_id, step_name, "empty log")
            ...  # the process
            audit.update(request_id, step_name, log_col="process log here")
        except Exception as exc:
            audit.update(request_id, step_name, error_column=f"{type(exc).__name__}: {exc}")
            raise

- audit.json maps each table to its stepNameList, auditflag and rollingSize; the step name alone
  picks the table (audit_config.py). A step whose table has auditflag false writes nothing, and a
  step listed in no table logs a warning and writes nothing.
- NOIDraftEntryAudit's stepNameList is shared: its first 13 steps are the draft RPA's
  (agents/agent_04/noi_draft_rpa, which writes them through its own copy of this package), the last
  three the queue endpoint's (agents/agent_04/noi_draft_queue/service.py).
- record() inserts the row (Timestamp = now, UTC), then trims the table to its rollingSize by
  deleting the oldest whole requests (never the current one). update() overwrites ErrorLog
  (error_column) and/or ActualLog (log_col) of that row; a column left out keeps its value.
- Nothing raises: a config or database problem is logged and the call returns False (0 for
  enforce_rolling_size), so auditing cannot break the process or hide its exception. Call
  load_audit_config() at start-up to fail fast on a bad audit.json.
- The database is packages.db (db.target in app.properties), imported on the first call: importing
  this package never connects. The table DDL is sql/NOIDraftEntryAudit.sql.
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
