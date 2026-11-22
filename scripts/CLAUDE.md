# scripts: one-off database jobs (create, migrate, seed)

## Purpose
Command-line scripts that change the Supabase database: create tables, apply schema migrations, load
pilot and demo data. They are the only migration mechanism (no Alembic). Not deployed (`.funcignore`).

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | makes `python -m scripts.<name>` work | – |
| `create_tables.py` | `Base.metadata.create_all` for missing ORM tables (runs `ddl.py` hooks) | `main()` |
| `create_audit_tables.py` | create every table in `packages/audit/audit.json` + enable RLS | `main()` |
| `migrate_cart_and_active_order.py` | add `users.cart`; `active_order_flag` boolean → smallint 0/1/2 + check | `main()` |
| `migrate_orders_review_id.py` | add `orders.review_id`, unique/FK constraints, backfill from reviews | `main()` |
| `migrate_users_app_installed.py` | add `users.app_installed` | `main()` |
| `seed_pilot_kitchens.py` | upsert pilot cooks/kitchens/dishes from `seed/pilot_kitchens.json` | `main()`, `upsert_user/kitchen/dishes` |
| `seed_demo_eat.py` | demo buyer, demo society, open dishes, 4 orders (`--dry-run`) | `seed()`, `run(work, dry_run)`, `find_pilot_kitchens`, `DEMO_SOCIETY_ID`, `DEMO_PHONE`, `DISH_PLAN`, `ORDER_PLAN` |
| `remove_demo_eat.py` | undo `seed_demo_eat` before production (`--dry-run`) | `remove()`, `remove_buyer`, `close_demo_dishes`, `clear_societies` |

## How it works
Run from the backend root: `python -m scripts.<name>` (imports `packages.*`, needs `DATABASE_URL` in
`.env`). Each script does all its work in one transaction (`engine.begin()`, `get_session()`, or
`seed_demo_eat.run`) and prints what it created/changed/skipped. `remove_demo_eat` imports constants
and helpers from `seed_demo_eat`, so the two must stay in sync.

## Invariants & gotchas
- Every script is safe to re-run: `IF NOT EXISTS`, `pg_constraint` / `information_schema` checks,
  upserts matched by natural keys (phone; kitchen name + main owner; kitchen + dish name; demo orders
  by `payment_id` `demo-seed-N`).
- Migrations `SET LOCAL lock_timeout = '5s'` before ALTERs so they fail fast instead of queueing live
  traffic. Run a migration **before** deploying code that reads the new column.
- `create_tables` never alters existing tables; column/constraint changes need a `migrate_*` script.
- `migrate_orders_review_id` aborts with nothing changed if an order has several reviews or
  `review_id` points at another order's review.
- `seed_demo_eat` only touches kitchens whose `society_id` is NULL or the demo society, and never
  modifies a reviewed order; times are relative to the run (re-run before a demo).
- `remove_demo_eat` re-implements the rating decrement inline (same as
  `record_rating_change(dish, rating, None)`) and clears `orders.review_id` before deleting reviews;
  it leaves Storage files and audit rows behind (prints the file paths).
- `seed_pilot_kitchens` never deletes dishes missing from the JSON; at most 3 owners per kitchen.

## How to extend
New migration: copy `migrate_users_app_installed.py` — docstring stating what changes, the run
command, "safe to re-run" and "run before deploying" → `with engine.begin() as conn:` +
`SET LOCAL lock_timeout = '5s'` + idempotent DDL (`IF NOT EXISTS`, or check `pg_constraint` first)
→ print the resulting state. Then update the model in `packages/database/models/` and `DATABASE.md`.

## Tests
None. `tests/test_order_review.py::test_schema_has_the_review_id_constraints_and_posts_audit` checks
that `migrate_orders_review_id` and `create_audit_tables` have been applied to the test database.
