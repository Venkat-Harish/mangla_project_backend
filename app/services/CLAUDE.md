# app/services: business logic, one module per endpoint group

## Purpose
Every query and write the endpoints run. Each public function takes the request's `Session` plus the
body fields, runs inside one `audit_step` or `log_step` ([../steps.py](../CLAUDE.md)), and returns a
schema object from `app/schemas/`.

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | package docstring | – |
| `account.py` | user row; app-installed flag (row-locked write) | `user_info` (logged), `update_installed` (audited) |
| `cart.py` | `users.cart` JSONB joined to current dish details | `user_cart` (logged) |
| `home.py` | pinned + society kitchens, pin/unpin, live/preorder kitchens | `kitchen_society_all`, `update_pinned`, `kitchen_live`, `kitchen_preorder`, `pinned_ids`, `LIVE_FLAGS`, `PREORDER_FLAGS` |
| `media.py` | signed upload URLs in the user's Storage folder | `upload_urls` (logged) |
| `orders.py` | order lists/details; reviewing an order | `user_all`, `user_kitchen`, `user_society`, `details`, `review`, `_check_reviewable` |
| `ratings.py` | `average_ratings` totals upkeep | `record_rating_change`, `DishRating` |
| `reviews.py` | review lists, edit, like counter; shared review helpers | `user_all`, `for_kitchen`, `for_dish`, `edit`, `like_counter`, `review_out`, `check_uploaded` |

Step names (audited ones must be in `packages/audit/audit.json`):
- orders_audit: `ordersUserAll`, `ordersUserKitchen`, `ordersUserSociety`, `ordersDetails`, `ordersReview`
- home_audit: `homeKitchenSocietyAll`, `homePinnedUpdate`, `homeKitchenLive`, `homeKitchenPreorder`
- review_audit: `reviewUserAll`, `reviewKitchen`, `reviewDish`, `reviewEdit`, `reviewLikeCounter`
- audited, no table yet: `accountInstalledUpdate` (in no `stepNameList`, so only logged + a warning)
- logged only (`log_step`): `accountUserInfo`, `cartUser`, `mediaUploadUrl`

## How it works
- Reads: `select(...)` with explicit joins (models have no `relationship()`), results via
  `.mappings()` → `Model.model_validate`. Lists are newest first with a tie-break on the ID.
- Images: one `storage.signed_images(kind, [paths lists], get_settings().storage_signed_url_seconds)`
  call per response signs everything at once ("dish" for dishes, "review" for reviews).
- Writes: read the row `with_for_update()`, mutate, `session.commit()` inside the step, then build the
  response from locals or a fresh query (`reviews.review_out`) because commit expires ORM objects.
- `orders.review` flow: lock-free read of the order → `_check_reviewable` (409 already reviewed / 422
  status not in `review.allowed_order_statuses`, casefolded) → `reviews.check_uploaded` (Storage) →
  lock the order (`with_for_update` + `populate_existing`) → re-check (catches a review saved
  meanwhile) → insert `Review` + `flush` → set `orders.review_id` → `record_rating_change(dish, None,
  rating)` → commit → `review_out(hide_anonymous=True)`.
- `ratings.record_rating_change(session, dish_id, old, new)`: one atomic
  `UPDATE average_ratings ... RETURNING`; old `None` = new review, new `None` = deleted review. No commit.

## Invariants & gotchas
- Call Storage (`check_uploaded`, signing) **before** taking row locks; never hold a lock across HTTP.
- Lock order for anything touching reviews: `orders` row → `all_reviews` insert/update →
  `average_ratings` row. Keep it for future delete/re-rate code, or two requests can deadlock.
- Every rating change (create, edit rating, delete) must call `record_rating_change` in the same
  transaction. Deleting a review must also clear `orders.review_id` first (FK has no ON DELETE).
  `scripts/remove_demo_eat.py` duplicates this logic inline.
- Anonymous reviews: `hide_anonymous=True` nulls `user_id`, `user_name` **and** `order_id`
  (`/orders/details` would reveal the user). Only `/review/user-all` shows them; `/review/edit`
  hides them too because the request doesn't name a requester.
- No authentication exists: IDs in the body are trusted as-is (Functions auth level is ANONYMOUS).
- JSONB columns (`pinned_kitchen`, `cart`, `images`) are not mutation-tracked: assign a new list.
  Stored data may be malformed; `pinned_ids` and `user_cart` skip bad entries with a warning.
- `active_order_flag`: 0 off, 1 live, 2 preorder; "live" lists include preorder (`LIVE_FLAGS = (1, 2)`).
- Removing review images only edits the list; files stay in Storage. Duplicated image paths are dropped.
- `like_counter` uses an atomic `UPDATE ... RETURNING`; the DB trigger does not stamp
  `last_edited_time` for like/dislike changes.
- `society_id=None` means "the user's own society"; a user without one gets an empty list, not 404.
- Response conventions: a single-row lookup that misses raises `NotFoundError` (404); a list filtered
  by an ID returns `[]` without checking the ID exists (`/orders/user-all`, `/review/kitchen`,
  `/home/kitchen-live`), unless the service must load that parent row anyway (`/cart/user`,
  `/orders/user-society` without `society_id` → 404). Lists are bare JSON arrays; nothing paginates.
- Step names are `<route group><Action>` in camelCase, the group spelled as in the URL
  (`ordersDetails`, `homePinnedUpdate`, `reviewLikeCounter` for `/review/...`).

## How to extend
- New endpoint: write `def thing(session, ...)` here wrapped in `audit_step("<group><Action>", **inputs)`
  (add the name to the right `stepNameList` in `packages/audit/audit.json` and to
  `tests/test_audit.py::test_every_audited_step_is_in_audit_json`) or `log_step(...)`; call
  `step.done("<short result>")`; raise only `app.errors` exceptions; commit before returning.
  Then route + schema (see [../routers/CLAUDE.md](../routers/CLAUDE.md)).
- Posts endpoints (none yet): `posts_audit` exists (auditflag true) with an empty `stepNameList`;
  steps would be `posts<Action>`. There is no posts media kind in `packages/storage` yet, and
  `posts.media_urls` has no reader or writer: decide its format (bucket paths, like every other media
  column, so it can be signed) before the first posts endpoint, and fix the model comment + `DATABASE.md`.
  Read posts with `post_deleted_flag` false (soft delete), newest by `posted_time`.
- Inputs passed to `audit_step` are JSON-dumped into logs and audit rows: pass IDs and counts, not
  whole texts or personal data.

## Tests
`tests/test_orders.py`, `test_order_review.py`, `test_reviews.py`, `test_home.py`,
`test_cart_account.py`, `test_media.py`, `test_ratings.py`; audit rows in `test_audit.py`.
