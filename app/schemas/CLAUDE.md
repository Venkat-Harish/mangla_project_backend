# app/schemas: Pydantic request bodies and response models (the API contract)

## Purpose
One module per endpoint group defining `*In` bodies and `*Out` responses, plus shared types in
`common.py`. Validation here is what turns bad input into a 422 before any query runs.

## Files
| File | Role | Key types / entry points |
|---|---|---|
| `__init__.py` | package docstring | – |
| `common.py` | shared types | `StorableText`, `ORMModel`, `ImageOut`, `UserIdIn`, `KitchenOut` |
| `account.py` | user row + installed flag | `UserOut`, `UpdateInstalledIn`, `InstalledOut` |
| `cart.py` | cart items | `CartItemOut`, `CartOut` |
| `home.py` | home screen | `KitchenSocietyAllIn`, `UpdatePinnedIn`, `SocietyIn`, `HomeKitchenOut`, `PinnedOut`, `ActiveDishOut`, `ActiveKitchenOut` |
| `media.py` | upload URLs | `UploadUrlIn`, `UploadOut`, `UploadUrlOut` |
| `orders.py` | orders + order review body | `Rating`, `ImagePath`, `OrderReviewIn`, `OrderOut`, `OrderListItem`, ID bodies |
| `reviews.py` | reviews | `ReviewEditIn`, `LikeCounterIn`, `ReviewOut`, `LikeCountsOut`, `KitchenIdIn`, `DishIdIn` |

## How it works
Routers declare the `*In` model as the body and the `*Out` as `response_model`. Services build
outputs with `Model.model_validate(orm_obj_or_row_mapping)` (`ORMModel` sets `from_attributes=True`)
or by keyword. Images in every output are `list[ImageOut]` = `{path, url}`; the service fills `url`
from `packages.storage.signed_images` (null if unsignable).

## Invariants & gotchas
- Any free text or path that will be stored in Postgres must be `StorableText` (rejects NUL and lone
  surrogates, which would otherwise make the INSERT a 500). `ImagePath` builds on it.
- `Rating` (Decimal, 0.5–5, multiple of 0.5) mirrors the DB check `ck_all_reviews_rating_half_stars`;
  change both together.
- `UserOut` and `OrderOut` list every column of `users` / `orders`; tests assert the exact key sets, so
  a new column means updating the schema and `test_cart_account.py::test_user_info` /
  `test_orders.py::test_details`.
- `services/home.py` fills `ActiveDishOut` by `getattr(dish, name)` for every field except `images`:
  each field there must be a `Dish` attribute. `KitchenOut` is filled from all `Kitchen` columns
  (extra keys are ignored by Pydantic).
- `ReviewOut.user_id`, `user_name`, `order_id` are optional because anonymous reviews null them.
- `model_copy(update=...)` skips validation, so services build `ImageOut(...)` explicitly there.
- Limits: `images` / `file_names` at most 10 items; `UploadUrlIn.kind` is `Literal["review"]`;
  `ReviewEditIn` needs at least one of `review_text` / `add_images` / `remove_images`.

## How to extend
New field on an output: add it here, make sure the service supplies it (ORM attribute or row key),
update the matching table in `docs/End-Points.md`. New body: subclass `BaseModel`, use `uuid.UUID`
for every `*_id` (all IDs are UUIDs; `*_alphanumeric_id` codes are output-only) and `StorableText`
for stored text, give optional fields a default. Reuse existing ID bodies (`UserIdIn` in `common.py`,
`KitchenIdIn`/`DishIdIn` in `reviews.py`; move one to `common.py` when a second group needs it).
`ImageOut` is used for videos too (any file in a media list).

## Tests
Exercised through the endpoint tests (`tests/test_*.py`); storable-text and rating edge cases in
`tests/test_order_review.py` (`test_bad_rating`, `test_text_postgres_cannot_store_is_a_422`).
