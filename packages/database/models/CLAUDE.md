# packages/database/models: ORM models, one file per table

## Purpose
SQLAlchemy 2.0 typed models for the 7 app tables. They are the schema source for
`python -m scripts.create_tables` and the query targets for `app/services`. Column-level docs and
the SQL live in [../../../DATABASE.md](../../../DATABASE.md).

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | imports every model (registers them on `Base.metadata`) | `__all__` of the 7 classes |
| `users.py` | `users`: phone (unique), society/flat, kitchen link, `pinned_kitchen`, `cart`, `app_installed` | `User` |
| `all_kitchens.py` | `all_kitchens`: name, society, up to 3 owners, `KIT-` id | `Kitchen` |
| `all_dishes.py` | `all_dishes`: price, `images`, `active_order_flag` 0/1/2, times, portions | `Dish` |
| `orders.py` | `orders`: kitchen/dish/user, status text, payment, `review_id`, `ORD-` id | `Order` |
| `all_reviews.py` | `all_reviews`: one per order, half-star rating, `images`, likes, `REV-` id | `Review` |
| `posts.py` | `posts`: `kitchen_id` (FK), `description`, `media_urls` JSONB list, `posted_time`, `last_edited_time`, `post_deleted_flag` (NOT NULL) + `post_deleted_time`, `PST-` id; no endpoints yet | `Post` |
| `average_ratings.py` | `average_ratings`: per-dish totals + computed `average_rating` | `AverageRating` |

## How it works
Each module defines a `Base` subclass with `Mapped[...]` columns, named indexes/check constraints in
`__table_args__`, then calls `ddl.py` helpers (`enable_rls` on every table except `users`,
`add_alnum_id_trigger`, edit/soft-delete triggers, `add_average_rating_rows`). Services import the
classes from `packages.database`. There are no `relationship()`s; queries join explicitly.

## Invariants & gotchas
- Class names differ from table names: `Kitchen`→`all_kitchens`, `Dish`→`all_dishes`,
  `Review`→`all_reviews`, `AverageRating`→`average_ratings`.
- Mutual foreign keys use `use_alter=True` with explicit names: `users.kitchen_id` ↔
  `all_kitchens.user_id1..3` (`users_kitchen_id_fkey`), `orders.review_id` ↔ `all_reviews.order_id`
  (`orders_review_id_fkey`, no ON DELETE: clear it before deleting a review).
- DB-filled columns are `FetchedValue()` (alphanumeric IDs, `post_deleted_time`) or
  `server_onupdate=FetchedValue()` (`last_edited_time`); never set them in Python.
  `average_rating` is a persisted `Computed` column; only the backend's `record_rating_change` moves
  `total_reviews_count` / `total_stars`.
- JSONB contents: `users.pinned_kitchen` list of kitchen-ID strings (nullable), `users.cart` list of
  `{"dish_id", "portion_count"}`, `all_dishes.images` / `all_reviews.images` lists of bucket paths
  (not URLs). `posts.media_urls` is commented (here and in `DATABASE.md`) as Storage URLs, but nothing
  reads or writes it yet; prefer bucket paths like the other media columns and fix the comment.
- `users.kitchen_flag` true marks a cook. `society_id` has no FK (no societies table yet).
- `users.py` has no `enable_rls` call (the other 6 tables do), though `DATABASE.md` shows RLS on in
  the live table. Add it if `users` is ever recreated from the model.
- Constraint/index names (`ck_*`, `ix_*`, `*_key`, `*_fkey`) are referenced by migration scripts and
  `tests/test_order_review.py`; don't rename them casually.
- Changing a model does **not** change the live database: `create_all` only creates missing tables.

## How to extend
- New column on an existing table: add it to the model → write an idempotent
  `scripts/migrate_<thing>.py` (see [../../../scripts/CLAUDE.md](../../../scripts/CLAUDE.md)) → run it
  before deploying code that reads the column → add it to the `*Out` schema if exposed (tests assert
  exact key sets for users/orders) → update the table section in `DATABASE.md`.
- New table: new `<table>.py` with the model + `enable_rls(...)` (+ `add_alnum_id_trigger` if it needs a
  readable ID) → import it in `models/__init__.py` and export it from `packages/database/__init__.py`
  → `python -m scripts.create_tables` → add a section and a row in the Tables list of `DATABASE.md`.

## Tests
Used by the `data` fixture in `tests/conftest.py`; constraints checked in `tests/test_ratings.py`,
`tests/test_order_review.py`, `tests/test_reviews.py`.
