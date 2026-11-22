# Mangla backend

Backend for Mangla, an app where residents of a housing society order from home kitchens: home
screen (society/pinned kitchens, live and preorder dishes), cart, orders, reviews with photos, and
signed media uploads. FastAPI on Azure Functions (Flex Consumption), Supabase Postgres + Storage.
There is no README yet; until one exists, the user-facing docs (and the ones to update for
user-visible changes) are [docs/End-Points.md](docs/End-Points.md) (API), [DATABASE.md](DATABASE.md)
(tables), [buckets.md](buckets.md) (Storage), [docs/Deployment.md](docs/Deployment.md) (Azure + CI/CD).

## Stack and commands
Python 3.14 (CI and the Function App), FastAPI 0.136.1, SQLAlchemy 2.0.45 + psycopg2-binary 2.9.11,
httpx 0.28.1, uvicorn 0.46.0, azure-functions 2.4.0, pytest 9.0.3 (`requirements.txt`, all pinned).
Secrets in `.env` (git-ignored): `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`.
Run everything from this folder (the backend root):

| Task | Command |
|---|---|
| Install | `pip install -r requirements.txt` |
| Run API (port 8000) | `python -m app` (or `uvicorn app.main:app --reload`) |
| Run as Functions host (port 7071) | `func start` (needs `local.settings.json`) |
| All tests (needs live Supabase `DATABASE_URL`) | `python -m pytest -q` |
| DB-free tests (what CI runs) | `python -m pytest tests/test_config.py --noconftest -q` |
| Create missing tables / audit tables | `python -m scripts.create_tables` / `python -m scripts.create_audit_tables` |
| Migrations, seeds | `python -m scripts.<migrate_*/seed_*/remove_demo_eat>` |
| Deploy | push to `main` → GitHub Actions `deploy.yml` → reviewer approves `production` |
| Lint / format | none configured |

## Architecture
```
client ── POST /app/<group>/<action>, JSON body
  │  uvicorn (python -m app)  or  Azure Functions host → function_app.py (AsgiFunctionApp)
  ▼
app/main.py  RequestIdMiddleware → CORS → UnhandledErrorMiddleware → exception handlers
  ▼
app/routers/<group>.py   body: app/schemas/<group>.py, db: Depends(get_db)
  ▼
app/services/<group>.py  with audit_step(...) / log_step(...)   (app/steps.py)
  ├─► packages/database   SQLAlchemy session → Supabase Postgres
  ├─► packages/storage    httpx → Supabase Storage (signed URLs, upload URLs, listing)
  └─► app/steps.audit_writer (thread, own pool) → packages/audit → *_audit tables
logging: every record carries the request ID → console + packages/common_logger files (masked)
```

## Code map
- [app/](app/CLAUDE.md): app factory, middleware, settings (`config.py`), `steps.py`, errors
- [app/routers/](app/routers/CLAUDE.md): the POST endpoints, thin
- [app/schemas/](app/schemas/CLAUDE.md): Pydantic bodies/responses, `StorableText`, `ImageOut`
- [app/services/](app/services/CLAUDE.md): all business logic, locking, ratings, anonymity
- [packages/audit/](packages/audit/CLAUDE.md): audit rows, `audit.json` step → table map
- [packages/common_logger/](packages/common_logger/CLAUDE.md): shared file logger + `masker`
- [packages/database/](packages/database/CLAUDE.md): engine, `SessionLocal`, DDL triggers
- [packages/database/models/](packages/database/models/CLAUDE.md): the 7 ORM tables
- [packages/storage/](packages/storage/CLAUDE.md): buckets, path rules, Storage HTTP calls
- [scripts/](scripts/CLAUDE.md): create/migrate/seed scripts
- [tests/](tests/CLAUDE.md): real-DB, rolled-back pytest suite
- `function_app.py`: Azure entry point wrapping `app.main:app`; `host.json` sets an empty route prefix
- `packages/db.py`: `Database`/`Repository` wrapper over the engine; imported nowhere (unused).
  `packages/__init__.py` is an empty package marker
- `app.properties`: non-secret settings; `logger.properties` / `logger.cloud.properties`: local / Azure logging
- `seed/pilot_kitchens.json`: pilot kitchen data for `scripts/seed_pilot_kitchens.py`
- `.github/workflows/deploy.yml`: test config → build `.python_packages` → approved deploy → smoke test
- `.funcignore`: keeps `tests/`, `scripts/`, `seed/`, `docs/`, `.env` out of the deployed package

## Rules that always hold
- **API shape:** every endpoint is `POST` with a JSON body under `api.prefix` (`/app`). Errors are
  `{"detail", "request_id"}` with 404/409/422 from `app/errors.py` exceptions, 502 from
  `StorageError`, 500 from anything else. Only `/orders/review` returns 201.
- **IDs:** every `*_id` (user, kitchen, dish, order, review, post, society) is a UUID, typed
  `uuid.UUID` in bodies. `*_alphanumeric_id` (`KIT-`/`ORD-`/`REV-`/`PST-XXXXXXXX`) are DB-generated
  display codes, never inputs.
- **No authentication:** IDs in the body are trusted (Functions `AuthLevel.ANONYMOUS`). Don't assume
  a caller identity exists.
- **Layering:** routers only call services; services take a `Session`, raise `app.errors`, and
  `commit()` their own writes before returning (`get_db` rolls back the rest).
- **Steps:** every service function runs in `audit_step` or `log_step`; an audited step name must be
  in a `stepNameList` of `packages/audit/audit.json` or nothing is written.
- **Media:** the DB stores bucket-relative paths, never URLs; responses return `{path, url}` with a
  short-lived signed URL (`storage.signed_url_seconds`). Saved paths must pass `is_in_folder` and
  exist in Storage. Call Storage before taking row locks.
- **Reviews/ratings:** one review per order; every rating change goes through
  `app/services/ratings.record_rating_change` in the same transaction; lock order orders →
  all_reviews → average_ratings. Anonymous reviews hide `user_id`, `user_name`, `order_id`
  everywhere except `/review/user-all`.
- **Text:** any client text stored in Postgres is typed `StorableText` (no NUL / lone surrogates).
- **Schema changes:** no Alembic. `create_all` only creates missing tables; anything else needs an
  idempotent `scripts/migrate_*.py` (with `lock_timeout`), run before deploying code that uses it,
  plus the model and `DATABASE.md`. New tables also need `enable_rls`.
- **Config/secrets:** secrets only in `.env` / Azure app settings; non-secrets in `app.properties`,
  overridable as `MANGLA_<KEY>` (dots → underscores). Never log secrets, phone numbers or names
  (the masker hides URL passwords and key=value secrets, not PII).
- **Logging:** `logging.getLogger(__name__)`; the request ID is added automatically.
- **Threads/processes:** sync endpoints run in Starlette's threadpool (request ID via ContextVar);
  audit rows go through one background thread with its own small pool. On Azure:
  `MANGLA_AUDIT_BACKGROUND=false`, `MANGLA_LOGGER_PROPERTIES=logger.cloud.properties` (read-only FS).

## Keeping docs current
- When you add, rename or delete a file, or change behaviour in a folder, update that folder's CLAUDE.md in the same change.
- A new folder with real logic gets its own CLAUDE.md (same headings) and a line in the code map.
- Edit this root file only when the architecture, commands or cross-cutting rules change. Keep it short.
- User-visible changes also update the README.
- Docs explain the why, the connections and the gotchas. Don't restate code line by line. Delete anything that's no longer true.
