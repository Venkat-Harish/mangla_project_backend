# common_logger

A small, reusable file logger for AARC Python projects (Python 3.11+, standard library only).
It plugs into Python's built-in `logging`, so code keeps using `logging.getLogger(__name__)`.

Each line looks like:

```
2026-10-03T14:05:22.123-05:00 | PID  1234 | TID 56780 | INFO     | 0.000 | steers_rpa.txr05.DraftFiller | [Filling NOI 12345]
2026-10-03T14:05:22.127-05:00 | PID  1234 | TID 56780 | INFO     | 0.004 | steers_rpa.txr05 | [Wizard page opened]
2026-10-03T14:05:23.460-05:00 | PID  1234 | TID 56780 | WARNING  | 1.333 | steers_rpa.txr05 | [Slow page]
2026-10-03T14:05:47.006-05:00 | PID  1234 | TID 56780 | INFO     | 23.54 | steers_rpa.txr05 | [Draft filled]
```

| Part | Example | Flag |
|---|---|---|
| Timestamp with UTC offset | `2026-10-03T14:05:22.123-05:00` | `include_timestamp` |
| Process ID | `PID  1234` | `include_process_id` |
| Thread ID (OS id) | `TID 56780` | `include_thread_id` |
| Level | `INFO    ` | `include_level` |
| Seconds since the previous line, or a given runtime | `0.004` / `23.54` | `include_elapsed` |
| Source (module path + class) | `steers_rpa.txr05.DraftFiller` | `include_source` |
| Message (always written) | `[Filling NOI 12345]` | (none) |

The columns before the source are fixed width, so the ` | ` separators line up like a table. The timestamp is always the same length, PID and TID are right-aligned to 5 digits (a longer id still prints in full), the level is padded to 8 characters (`CRITICAL`), and the seconds field is 5 characters (4 digits and a dot). The source path is not padded.

The seconds field:
- By default it is the time since the previous line from the same process, in seconds. It equals the difference of the two timestamps.
- It always uses 4 digits and a dot; decimals that don't fit are cut, not rounded: 4 ms is `0.004`, 23 s 546 ms is `23.54`, 123 s 456 ms is `123.4`, 1234 s is ` 1234`. 10000 s (2.7 hours) or more prints in full.
- The first line of each process shows `0.000`. The line above it in the file came from another process, such as an earlier run, and is ignored.
- If the code passes its own runtime, that is shown instead: `logger.info("Draft filled", extra={"runtime": 23.546})` gives `23.54`. The next line's gap is still measured from this line.

## Usage

```python
# main.py, called once when the program starts
import sys
sys.path.append(r"C:\...\agent04-d-noi-fabric-draft")   # folder that contains packages/, or set PYTHONPATH

from packages.common_logger import LogSetup
LogSetup.configure(r"C:\...\my_project\logger.properties")   # no argument = the bundled logger.properties
```

```python
# any module in the project
import logging
logger = logging.getLogger(__name__)

class DraftFiller:
    def fill(self, ref):
        logger.info("Filling NOI %s", ref)
        logger.debug("Wizard page opened")
        logger.error("NOI %s not found", ref)
        try:
            ...
        except Exception:
            logger.exception("Draft fill crashed")   # also writes the traceback inside [ ]
        logger.warning("Slow page", stack_info=True)    # stack_info is written inside [ ] too
        logger.info("Draft filled", extra={"runtime": 23.546})   # shows 23.54 instead of the gap
```

## Settings (`logger.properties`)

Copy `logger.properties` into your project and change it there; see the comments in the file.

| Key | Meaning |
|---|---|
| `logging_enabled` | `false` writes no folder and no files; other root handlers (e.g. the console) are still masked |
| `log_directory` | Folder for log files (relative = relative to the properties file) |
| `log_file_prefix` | File name prefix: `<prefix>_YYYY-MM-DD_HH-MM-SS_ffffff.log` |
| `max_file_size_mb` | When the next line would push a file past this size, a new timestamped file is started in the same folder |
| `log_level` | Minimum level written: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `mask_sensitive_data` | `true` masks PII such as ER numbers (see Masking); `false` shows them in full |
| `include_*` | Turn each line part on or off |

On start-up the logger keeps appending to the newest `<prefix>_*.log` file in the folder until it is full.

## Masking

All masking lives in one class, `LogMasker` in `log_masker.py`. One shared instance, `masker`, is used by the logger and by code that masks its own text (`from packages.common_logger import masker`).

- Every finished log line, including any traceback, goes through `masker.mask()`. `LogSetup.configure` also wraps the formatter of any other root handler (e.g. a console from `logging.basicConfig`), so console lines are masked the same way. This happens even with `logging_enabled=false`: a container that ships only its console output (e.g. to Log Analytics) still gets masked lines.
- `mask_sensitive_data` switches the PII rules (`pii_rules`, today ER numbers: `ER000000` -> `ER****00`) on or off everywhere, including the code's own `masker.mask_er_number(...)` calls. It defaults to `true`.
- Always masked, whatever the flag (`always_rules` plus explicit secrets):
  - URL session tokens: `log=abc123` -> `log=...`
  - key=value secrets: the value of `PWD`, `Password`, `AccountKey`, `SharedAccessSignature`, `sig` and `ClientSecret` / `client_secret` (any case) becomes `***` and the key stays, e.g. `UID=svc;PWD=abc;Encrypt=yes` -> `UID=svc;PWD=***;Encrypt=yes` and `...&sig=abc` -> `...&sig=***`. The value runs to the next `;`, `&`, whitespace or the end of the text; an ODBC value in braces (`PWD={a;b}`) is masked whole. A plain sentence such as "the password was rejected" (no `=`) is left alone.
  - any secret values passed in, e.g. `masker.mask(text, secrets=[password])` -> `***`.

To add a rule, add a method that takes text and returns it masked, then list its name in `pii_rules` (follows the flag) or `always_rules` (never switched off):

```python
class LogMasker:
    EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    pii_rules = ("mask_er_numbers", "mask_emails")

    def mask_emails(self, text):
        return self.EMAIL.sub("***@***", text)
```

## Notes

- Give each project its own `logger.properties` and log folder.
- Want console output too? Call `logging.basicConfig(...)` **before** `LogSetup.configure(...)`; `basicConfig` does nothing once the root logger already has a handler. Note that `log_level` becomes the root logger level, so the console follows it too.
- `log_directory` expands environment variables: `$VAR` / `${VAR}` everywhere, `%VAR%` on Windows only.
- Azure Functions: copy the `packages/common_logger` folder into the function app; a `sys.path` entry to a sibling folder will not exist there.
- In this repo's Function App (repo-root `packages/`), do not call `LogSetup.configure()`: it would wrap every root handler, the host's and every agent's included. Use `logging.getLogger(__name__)` and pass free text through `masker.mask()`.
- A failed write (full disk, lost file share, OneDrive sync lock) never reaches the code that logged: the line is dropped from the file and one masked `--- Logging error: ...` line goes to stderr instead (nothing when `logging.raiseExceptions` is `False`). The log folder itself is still created in `LogSetup.configure`, so a folder that cannot be created fails there, at start-up.
- Not handled yet: bad property values, several processes sharing one log file, deleting old files. Keep `log_directory` outside OneDrive.
