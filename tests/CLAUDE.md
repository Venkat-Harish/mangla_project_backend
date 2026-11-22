# tests: pytest suite against the real Supabase database (rolled back)

## Purpose
Endpoint, service and package tests. They run against the Postgres in `DATABASE_URL` inside one
transaction per test that is rolled back; Storage is faked and auditing is off unless a test opts in.

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | package marker (tests import `tests.conftest.signed`) | – |
| `conftest.py` | fixtures and helpers | `db`, `client`, `data` (`Data`), autouse `fake_storage` (`FakeStorage.uploaded`), autouse `no_audit`, `signed(bucket, path)`, `live_storage` marker |
| `test_app.py` | request IDs, error bodies, CORS on 500, log forging, exact count of POST routes | – |
| `test_audit.py` | audit.json contents, real audit rows (deleted after), writer queue/flush | `audit_on` fixture |
| `test_cart_account.py` | `/cart/user`, `/account/user-info`, `/account/update-installed` | – |
| `test_config.py` | `MANGLA_<KEY>` overrides; needs no DB | – |
| `test_home.py` | `/home/*` ordering, pinning, live/preorder, signed dish images | – |
| `test_media.py` | `/media/upload-url` paths and validation | – |
| `test_order_review.py` | `/orders/review`: success, 404/409/422/502, race, anonymity, settings, storable text | – |
| `test_orders.py` | order lists and details | – |
| `test_ratings.py` | `record_rating_change` and `average_ratings` constraints | – |
| `test_reviews.py` | review lists, anonymity, edit, like counter | – |
| `test_storage_live.py` | real Storage calls, nothing written | `live_storage`, skipped without keys |
| `test_storage_paths.py` | path rules, no network | – |

## How it works
- `db`: a connection with an open transaction; the `Session` uses
  `join_transaction_mode="create_savepoint"`, so a service's `commit()` only releases a savepoint and
  everything is rolled back at the end.
- `client`: `TestClient(app)` with `get_db` overridden to return that same `db` session, so the test
  sees what the request wrote (call `db.expire_all()` before re-reading).
- `data`: two random societies; customer (society A, pins kitchen B, 2 cart entries — one dish
  missing), other user, owner; kitchens A1 (live/preorder/off dishes), A2 (off), B (live); orders
  `order_old`, `order_new` (both reviewed, ratings recorded) and `order_b` (delivered, unreviewed);
  `review_anon` (customer, anonymous, one image) and `review_named` (other user).
- `fake_storage`: every path signs to `https://signed/<bucket>/<path>`; upload URLs are fake; only paths
  added to `fake_storage.uploaded` "exist". Mark a test `live_storage` to use the real client.

## Invariants & gotchas
- Everything except `test_config.py` needs a reachable Supabase `DATABASE_URL` (importing `app.main`
  raises without it). CI runs only `python -m pytest tests/test_config.py --noconftest -q`.
- Writes are real but rolled back; `test_audit.py` writes real audit rows on its own connection and
  deletes them by request ID afterwards.
- Audit is disabled by monkeypatching `audit_writer.enabled`; enable it only through `audit_on`.
- Fixture rows use random UUIDs/phones, so tests can run against a database with real data. No
  separate test-database config exists (the docs name one Supabase project): check which database
  `.env` points at before running the suite.
- `data` has no posts; a posts test inserts its own `Post` rows.
- `get_settings` is cached per path: config tests write a fresh `app.properties` in `tmp_path`.
- Error tests assert `request_id` in the body equals the `X-Request-ID` header; keep doing that.

## How to extend
New endpoint test: take `client` + `data` (+ `db`, `fake_storage`), post JSON to `/app/...`, assert
status, body, and DB state after `db.expire_all()`. Add audited step names to
`test_every_audited_step_is_in_audit_json`; bump the route count in `test_app.py`. Need new rows?
Add them in the test, or extend `Data` in `conftest.py` if many tests need them.

## Tests
Run from the backend root: `python -m pytest -q` (full suite), or
`python -m pytest tests/test_config.py --noconftest -q` (no database).
