# packages/common_logger: shared AARC file logger with masking

## Purpose
Rolling log files with a fixed column layout, and one `LogMasker` that masks secrets in every log
line and in audit text. Reused from another AARC project (examples mention STEERS / `steers_rpa`);
user-level docs are in [README.md](README.md) — read that for line format and settings.

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | exports | `LogSetup`, `LogMasker`, `masker` |
| `log_setup.py` | one-time root-logger setup | `LogSetup.configure(properties_path)` |
| `log_config.py` | parse a logger `.properties` file | `LogConfig` |
| `log_formatter.py` | builds `ts \| PID \| TID \| LEVEL \| elapsed \| REQ id \| source \| [msg]`, then masks it | `LogLineFormatter`, `format_seconds` |
| `log_handler.py` | append to newest `<prefix>_<timestamp>.log`, roll over at max size | `RolloverFileHandler` |
| `log_masker.py` | all masking rules | `LogMasker`, `MaskingFormatter`, shared `masker` |
| `logger.properties` | bundled defaults (prefix `app`, no request ID); the API does not use it | – |
| `README.md` | full user documentation | – |

## How it works
`app/logging_setup.configure_logging()` adds a console handler, installs a LogRecord factory that sets
`record.request_id`, then calls `LogSetup.configure(settings.logger_properties)` — the repo-root
`logger.properties` locally (files in `logs/`, prefix `mangla_api`, request ID column on) or
`logger.cloud.properties` on Azure (`logging_enabled=false`). `configure` sets `masker.enabled` from
`mask_sensitive_data`, wraps every other root handler's formatter in `MaskingFormatter`, and (if
enabled) adds `RolloverFileHandler` + `LogLineFormatter` and sets the root level to `log_level`.

## Invariants & gotchas
- Always masked: URL passwords (`postgresql://user:***@host`, i.e. `DATABASE_URL`), key=value secrets
  (`PWD=`, `Password=`, `AccountKey=`, `sig=`, `ClientSecret=` ...), URL session tokens, registered
  secrets. The only PII rule (`pii_rules`) masks "ER numbers"; **phone numbers and names are not
  masked** (`User.__repr__` contains `phone_number`), so don't log them.
- `masker` is a process-wide singleton also used by `packages/audit` for stored audit text.
- Call order matters: handlers added before `LogSetup.configure` get masked; a second `configure`
  replaces the file handler rather than duplicating it.
- `include_request_id` defaults to false in `LogConfig`; the repo-root `logger.properties` turns it on.
- Old log files are never deleted; several processes sharing one log folder is not handled.
- Needs Python 3.11+ (`sys.exception()`, `co_qualname`).

## How to extend
New masking rule: add a method `mask_x(self, text) -> str` to `LogMasker` and list it in `pii_rules`
(switched by `mask_sensitive_data`) or `always_rules`; update the Masking section of `README.md`.
New line part: flag in `LogConfig`, part in `LogLineFormatter.format`, key in the `.properties`
files, row in the README table.

## Tests
None directly. `tests/test_app.py::test_path_cannot_forge_log_lines` and
`tests/test_audit.py::test_cart_and_account_are_logged_not_audited` check request IDs on log records.
