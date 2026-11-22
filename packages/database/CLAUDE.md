# packages/database: Supabase Postgres engine, sessions and DDL hooks

## Purpose
The one SQLAlchemy engine for requests and scripts, the declarative `Base`, and the database-level
SQL (functions, triggers, RLS) that `create_all` runs when it creates a table. ORM models are in
[models/](models/CLAUDE.md); table-by-table docs in [../../DATABASE.md](../../DATABASE.md).

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | public API | `Base`, `SessionLocal`, `engine`, `get_session`, `run_query`, all 7 models |
| `base.py` | declarative base | `Base(DeclarativeBase)` |
| `db.py` | loads `.env`, builds the engine | `engine`, `SessionLocal`, `get_session()` (commit/rollback context manager), `run_query(sql, params)`, `DATABASE_URL` |
| `ddl.py` | SQL `create_all` can't express, attached via DDL events | `add_alnum_id_trigger`, `add_review_edit_trigger`, `add_last_edited_trigger`, `add_post_deleted_time_trigger`, `add_average_rating_rows`, `enable_rls` |

## How it works
- `db.py` runs `load_dotenv(<backend root>/.env)` at import and raises `RuntimeError` if
  `DATABASE_URL` is unset; `create_engine(..., pool_pre_ping=True, connect_args={"connect_timeout": 10})`
  connects lazily. Requests get sessions through `app/deps.get_db` (`SessionLocal`); scripts use
  `get_session()` or `engine.begin()`.
- `ddl.py` registers `generate_alnum_code` and `set_alnum_id` on `Base.metadata` "before_create";
  each model file calls the `add_*`/`enable_rls` helpers, which listen on that table's
  "after_create" (and "before_create" for their trigger function).
- Generated IDs: `set_alnum_id(column, prefix)` fills `PREFIX-XXXXXXXX` (alphabet without 0/O/1/I),
  retrying until unused: `KIT-`, `ORD-`, `REV-`, `PST-`.
- Other triggers: `all_reviews` stamps `last_edited_time` only when rating/text/images/anonymous change;
  `posts` stamps `last_edited_time` on description/media_urls and keeps `post_deleted_time` in step
  with `post_deleted_flag`; creating `average_ratings` backfills one row per dish and adds an
  `all_dishes` trigger that inserts/syncs a row for every new dish.

## Invariants & gotchas
- DDL hooks run **only when `create_all` creates that table**. For an existing table, a new trigger,
  constraint or column must be applied by a `scripts/migrate_*.py` script.
- SQLAlchemy %-formats DDL strings: never write `%` in `ddl.py` SQL (use `mod()`, `quote_ident()`).
- Trigger functions use `SET search_path = ''` and schema-qualify everything (`public.`).
- Tables get `enable_rls` with no policies: it blocks Supabase's public (PostgREST) API, while the
  backend connects as `postgres` and bypasses RLS (per `DATABASE.md`). `models/users.py` does not
  call `enable_rls`, although the live `users` table has RLS on: a fresh `create_all` would miss it.
- Two pools exist per process: this engine, and the small audit engine in `app/steps.py`.
  `packages/db.py` (`Database`/`Repository`) wraps this engine but nothing imports it.
- On Azure, `DATABASE_URL` is the Supabase transaction pooler (port 6543); see `docs/Deployment.md`.
- `SessionLocal` uses the default `expire_on_commit=True`: attributes reload after commit.

## How to extend
- New reusable trigger: SQL function as a `DDL(...)` constant + an `add_*(table, ...)` helper that
  listens on "before_create"/"after_create"; call it from the model module; also write a migration
  script that installs it on tables that already exist; describe it in `DATABASE.md`.
- New table or column: see [models/CLAUDE.md](models/CLAUDE.md).

## Tests
Indirect: every DB test uses `engine` via `tests/conftest.py`. `tests/test_ratings.py` checks the
average_ratings trigger/constraints; `test_reviews.py` the last-edited trigger; ID prefixes are
asserted in `test_orders.py` / `test_reviews.py`.
