# packages/audit: request-audit rows in the Supabase *_audit tables

## Purpose
Writes one row per (request ID, step name) to the audit table that `audit.json` assigns to the step.
Generic (knows nothing about FastAPI); the API drives it from `app/steps.py`.

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | public API + long usage docstring | re-exports `Audit`, `audit`, `AuditConfig`, `AuditConfigError`, `TableSettings`, `load_audit_config` |
| `audit.json` | table → `stepNameList`, `auditflag`, `rollingSize`, optional `schema` | `orders_audit`, `review_audit`, `home_audit`, `posts_audit` (empty list): all `auditflag: true`, `rollingSize: 10000`, schema `public` |
| `audit_config.py` | load + validate `audit.json`, build step → table map | `load_audit_config()` (cached per path), `AuditConfig.table_for()`, `TableSettings` |
| `audit_store.py` | the writes and SQL builders | `Audit.write/record/update/enforce_rolling_size`, `build_audit_table`, `build_audit_trim`, `TRIM_EVERY_WRITES = 100`, shared `audit` |

## How it works
- The API path: `app/steps.py` creates its own `Audit(session_factory=<small pool>)` and, when an
  `audit_step` ends, calls `Audit.write(request_id, step, log_col=..., error_column=..., timestamp=...)`
  from the background writer thread. `write` = one `INSERT ... ON CONFLICT (request_id, step_name)
  DO UPDATE` transaction, then a rolling-size trim on the table's 1st write in this process and every
  100th after.
- `record()` (insert + trim every time) and `update()` (overwrite given log columns) are the
  two-call alternative from the package docstring; the API does not use them.
- `_target()` resolves the step: unknown step → warning, nothing written; `auditflag: false` →
  debug log, nothing written; request ID must be a UUID.
- `build_audit_trim` deletes whole oldest requests (ranked by first timestamp) once the running row
  count passes `rollingSize`, never the current request, in one statement.
- Log text is masked with `packages.common_logger.masker` before it is stored.

## Invariants & gotchas
- Nothing raises into the caller: config/DB problems are logged and the call returns False (0 for
  trims). A bad `audit.json` logs at ERROR on every call; call `load_audit_config()` at start-up to
  fail fast.
- `audit.json` rules (enforced in `_check_config`): table/schema names are plain lowercase Postgres
  identifiers ≤63 chars; only keys `_comment`, `stepNameList`, `auditflag`, `rollingSize`, `schema`;
  a step belongs to one table, and names differing only by case are refused; duplicate JSON keys are
  refused; `rollingSize` ≥ 1 (default 10000).
- Tables are not created by this package: a new table in `audit.json` needs
  `python -m scripts.create_audit_tables` before deploy, or every write to it fails (warning).
- The trim counter is per process, so with several Function instances a table can overshoot
  `rollingSize` by up to ~100 rows per instance between trims.
- Importing the package never connects; the default `audit` instance imports
  `packages.database.db.SessionLocal` on first use (needs `DATABASE_URL`).
- `timestamp` is the step's start time when the caller passes it (the API does), else the DB's `now()`.

## How to extend
- New audited step: add its name to the right `stepNameList` in `audit.json`, use
  `audit_step("<name>", ...)` in the service, and add it to
  `tests/test_audit.py::test_every_audited_step_is_in_audit_json`.
- New audit table (e.g. for account): add an entry to `audit.json`, run
  `python -m scripts.create_audit_tables`, add a section to `DATABASE.md`, and update the table set
  asserted in `test_every_audited_step_is_in_audit_json`.

## Tests
`tests/test_audit.py`: config contents, success/failure rows reaching Supabase (deleted afterwards),
`/orders/review` audited, cart/account not audited, `AuditWriter` queue bound and flush deadline.
