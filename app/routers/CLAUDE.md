# app/routers: HTTP endpoints, one thin module per endpoint group

## Purpose
Declares every route (all `POST` with a JSON body) and hands the validated body to the matching
service function. No logic lives here.

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | package docstring | – |
| `account.py` | `/account/user-info`, `/account/update-installed` | `router` → `services.account` |
| `cart.py` | `/cart/user` | `router` → `services.cart.user_cart` |
| `home.py` | `/home/kitchen-society-all`, `/home/update-pinned`, `/home/kitchen-live`, `/home/kitchen-preorder` | `router` → `services.home` |
| `media.py` | `/media/upload-url` | `router` → `services.media.upload_urls` |
| `orders.py` | `/orders/user-all`, `/orders/user-kitchen`, `/orders/user-society`, `/orders/details`, `/orders/review` (201) | `router` → `services.orders` |
| `reviews.py` | `/review/user-all`, `/review/kitchen`, `/review/dish`, `/review/edit`, `/review/like-counter` | `router` (prefix `/review`, singular) → `services.reviews` |

## How it works
`APIRouter(prefix="/<group>")`; `app/main.py` mounts each under `api.prefix` (default `/app`), giving
routes such as `POST /app/orders/details`. Each handler is a sync `def`, takes a body model from
`app/schemas/` plus `db: Session = Depends(get_db)`, and returns the service's result; `response_model`
filters/validates the output. Handler docstrings become the OpenAPI descriptions.

## Invariants & gotchas
- Keep handlers sync `def`: services do blocking SQLAlchemy/httpx calls, and the threadpool is what
  keeps them off the event loop (the request-ID ContextVar is copied into it).
- Every route is `POST` even for reads; `tests/test_app.py::test_routes_are_post_under_app_prefix`
  asserts all `/app/` routes are POST and their exact count (18 today). Adding or removing a route
  means updating that count there (this doc doesn't need the number).
- File `reviews.py` serves the `/review/...` prefix, not `/reviews/`.
- Only `/orders/review` returns 201; everything else is 200.

## How to extend
New endpoint: body/response models in `app/schemas/<group>.py` → service function in
`app/services/<group>.py` (wrapped in `audit_step`/`log_step`) → handler here → if it is a new
module, add it to the tuple in `create_app()` (`app/main.py`) → bump the route count in
`tests/test_app.py` → add tests → document it in `docs/End-Points.md`.

## Tests
`tests/test_app.py` (route layout), plus the per-group endpoint tests: `test_orders.py`,
`test_order_review.py`, `test_reviews.py`, `test_home.py`, `test_cart_account.py`, `test_media.py`.
