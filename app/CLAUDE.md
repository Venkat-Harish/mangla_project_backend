# app: the FastAPI application (factory, middleware, settings, steps, errors)

## Purpose
Builds the ASGI app that both uvicorn (`python -m app`) and Azure Functions (`function_app.py`) serve.
The top-level modules here are plumbing; endpoint logic lives in [routers/](routers/CLAUDE.md),
[schemas/](schemas/CLAUDE.md) and [services/](services/CLAUDE.md).

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | package marker (docstring only) | – |
| `__main__.py` | `python -m app`: uvicorn with host/port/reload from settings | – |
| `main.py` | app factory, middleware, exception handlers, router mounting, lifespan | `create_app()`, module-level `app`, `AsciiJSONResponse`, `lifespan` |
| `config.py` | settings from `app.properties` + `MANGLA_<KEY>` env overrides | `get_settings()` (cached), `Settings`, `env_name()`, `read_properties()` |
| `deps.py` | per-request DB session dependency | `get_db()` |
| `errors.py` | the exceptions services raise | `NotFoundError` (404), `ConflictError` (409), `InvalidInputError` (422) |
| `logging_setup.py` | console handler + common_logger files, request ID on every record | `configure_logging()` |
| `request_id.py` | uuid4 per request, JSON 500 for unhandled errors | `RequestIdMiddleware`, `UnhandledErrorMiddleware`, `get_request_id()` |
| `steps.py` | log + audit wrapper every service function runs in; audit writer thread | `audit_step()`, `log_step()`, `Step.done()`, `AuditWriter`, `audit_writer`, `audit_store` |

## How it works
- Import of `app.main` runs `create_app()`: `get_settings()` → `configure_logging()` → middleware →
  exception handlers → `include_router` for `(orders, home, cart, account, reviews, media)` under
  `settings.api_prefix` (default `/app`). Importing it also imports `app.steps` and
  `packages.database`, so **`DATABASE_URL` must be set to import the app** (no connection is opened).
- Per request, outermost first: `RequestIdMiddleware` (new uuid4 in a ContextVar, `X-Request-ID`
  response header, "Request received/finished" log lines) → `CORSMiddleware` (exposes the request-ID
  header) → `UnhandledErrorMiddleware` (turns an escaped exception into
  `{"detail": "Internal server error", "request_id"}` 500 *inside* CORS) → route.
  `add_middleware` wraps, so the code adds them in reverse order.
- Exception handlers map `NotFoundError`/`ConflictError`/`InvalidInputError` → 404/409/422,
  `StorageError` → 502, Starlette `HTTPException` (incl. unknown route 404/405) and
  `RequestValidationError` → 422. Every error body is `{"detail": ..., "request_id": ...}` rendered
  with `AsciiJSONResponse` (ASCII-escaped, so echoed lone surrogates can't turn a 422 into a 500).
- Routes are sync `def`, so Starlette runs them in its threadpool; the context (request ID) is copied
  there. `get_db()` yields a `SessionLocal()` and always `rollback()` + `close()` afterwards.
- `audit_step(name, **inputs)` / `log_step(...)` (context managers) log `<step> started: <inputs JSON>`
  and `finished in N ms: <Step.done text>` / `failed ...`. `audit_step` also submits one
  `audit_store.write(...)` row (timestamp = step start, `actual_log` = `<inputs> -> <result> (N ms)`,
  `error_log` on failure) to `audit_writer`, but only inside a request (needs a request ID).
- `audit_writer`: with `audit.background=true` one daemon thread `audit-writer` runs writes in order,
  each in a copy of the submitting request's context; queue bounded by `audit.max_pending`
  (overflow is dropped + warned). `lifespan` shutdown calls `audit_writer.flush(audit.flush_timeout_seconds)`.
  Audit rows use their own engine (`pool_size=1, max_overflow=4, pool_timeout=5`, connect timeout 5 s),
  never the request pool.

## Invariants & gotchas
- Services must `session.commit()` their own writes before returning: `get_db` rolls back whatever is
  uncommitted, and committing after the response would hide a failed commit behind a 200.
- `get_settings()` is `functools.cache`d per path: values are read once per process; env changes after
  import have no effect. Booleans are true only for the literal `true` (any case).
  `api.prefix` `/` becomes `""`; relative `logger.properties` resolves from `app.properties`' folder.
- The incoming `X-Request-ID` header is ignored; the server always generates a new uuid4.
- Request paths are re-percent-encoded before logging (`_loggable_path`) so clients can't forge log
  lines; validation summaries are logged with `%r` for the same reason. Keep both.
- `steps._CALLER = 3` is the `stacklevel` that makes step log lines name the calling service. Adding a
  wrapper layer around `_step` shifts it.
- Client-caused errors (`_EXPECTED_ERRORS` in `steps.py`) log as WARNING, everything else as ERROR.
- On Azure, `MANGLA_AUDIT_BACKGROUND=false` (shutdown flush isn't guaranteed) and
  `MANGLA_LOGGER_PROPERTIES=logger.cloud.properties` (read-only filesystem): see `docs/Deployment.md`.
- Audit step names must be listed in `packages/audit/audit.json` or the row is silently skipped
  (a warning is logged).

## How to extend
- New setting: key + comment in `app.properties` → field in `Settings` → parse in `get_settings()` with
  a default → read via `get_settings().<field>`. If Azure needs a different value, add it to the
  app-settings table in `docs/Deployment.md`. Extend `tests/test_config.py` if parsing is non-trivial.
- New error type: class in `errors.py` (with `.detail`) → `@app.exception_handler` in `create_app()`
  → add to `_EXPECTED_ERRORS` in `steps.py` if the client causes it → document the code in
  `docs/End-Points.md`.
- New endpoint group: router module in `routers/`, then add it to the `for module in (...)` tuple in
  `create_app()` (see [routers/CLAUDE.md](routers/CLAUDE.md)).

## Tests
`tests/test_app.py` (request IDs, error bodies, CORS on 500, log forging, route count),
`tests/test_config.py` (env overrides, no DB), `tests/test_audit.py` (`AuditWriter` queue/flush, audit
rows per request).
