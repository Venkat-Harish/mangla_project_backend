# API Endpoints

All endpoints are `POST` with a JSON body, mounted under `api.prefix` (default `/app`), e.g. `POST /app/account/user-info`.
IDs are UUIDs. `?` = optional. Errors: `404` not found, `422` invalid body or input not allowed, `502` file storage unavailable (all include `request_id`).

## Media files
Photos and videos live in private Supabase Storage buckets ([buckets.md](../buckets.md)); `packages/storage` does every Storage call.

| Field | Bucket | Path of each file |
|---|---|---|
| Dish `images` (Cart, Home) | `dish_and_kitchen_photos_videos` | `dishes_pics/<kitchen_id>/<dish_id>/<file>` |
| Review `images`, `/review/edit` `add_images[]` / `remove_images[]` | `reviews_photos_and_videos` | `users/<user_id>/<file>` (the reviewer's `user_id`) |

- The database stores each file's **path** inside its bucket. Every `images` field in an output is a list of **Image**: `{path, url}`. `url` is a signed URL, valid for `storage.signed_url_seconds` (app.properties, default 3600 s); it is `null` when the file can't be signed (not uploaded, or Storage down), and the rest of the response is still returned.
- Inputs that name images (`add_images[]`, `remove_images[]`) take **paths**, the `path` of an Image.
- Allowed file types: `jpg jpeg png webp heic gif mp4 mov webm`.
- **Uploading** (folders appear with their first file; nothing to create):
  1. `/media/upload-url` with the file names: returns a `path` and an `upload_url` per file.
  2. `PUT` each file's bytes to its `upload_url` (valid for 2 hours).
  3. Send the paths to the endpoint that saves them, e.g. `/review/edit` `add_images[]`.

## Account
| Endpoint | Input | Output | Description |
|---|---|---|---|
| `/account/user-info` | `user_id` | User (all user columns) | Everything stored about the user. |

## Cart
| Endpoint | Input | Output | Description |
|---|---|---|---|
| `/cart/user` | `user_id` | `{user_id, items[]}` | Items in the user's cart with current dish details. |

Cart item: `dish_id, portion_count, available, dish_name, dish_price, images` (Image[]) `, active_order_flag, kitchen_id, kitchen_name`

## Home
| Endpoint | Input | Output | Description |
|---|---|---|---|
| `/home/kitchen-society-all` | `user_id`, `society_id?` | Kitchen[] + `pinned` | Pinned kitchens first, then the rest of the society (default: user's society). |
| `/home/update-pinned` | `user_id`, `kitchen_id`, `pin?` (default `true`) | `{user_id, pinned_kitchen[]}` | Pin / unpin a kitchen. |
| `/home/kitchen-live` | `society_id` | Kitchen[] + `dishes[]` | Kitchens with a dish where `active_order_flag` is 1 or 2. |
| `/home/kitchen-preorder` | `society_id` | Kitchen[] + `dishes[]` | Kitchens with a dish where `active_order_flag` is 2. |

Kitchen: `kitchen_id, kitchen_alphanumeric_id, kitchen_name, society_id, user_id1, user_id2, user_id3`
Dish: `dish_id, dish_name, dish_price, images` (Image[]) `, description, active_order_flag, order_close_time, pickup_time, portions_count`

## Orders
| Endpoint | Input | Output | Description |
|---|---|---|---|
| `/orders/user-all` | `user_id` | Order[] + `kitchen_name, dish_name` | All the user's orders, newest first. |
| `/orders/user-kitchen` | `user_id`, `kitchen_id` | Order[] + `kitchen_name, dish_name` | User's orders from one kitchen. |
| `/orders/user-society` | `user_id`, `society_id?` | Order[] + `kitchen_name, dish_name` | User's orders in a society (default: user's own). |
| `/orders/details` | `order_id` | Order | One order, every column. |

Order: `order_id, order_alphanumeric_id, kitchen_id, dish_id, user_id, portion_count, order_time, order_status, payment_id, refund_flag`

## Review
| Endpoint | Input | Output | Description |
|---|---|---|---|
| `/review/user-all` | `user_id` | Review[] | Every review the user wrote, newest first. |
| `/review/kitchen` | `kitchen_id` | Review[] | Reviews of all the kitchen's dishes (anonymous reviewers hidden). |
| `/review/dish` | `dish_id` | Review[] | Reviews of one dish (anonymous reviewers hidden). |
| `/review/edit` | `review_id`, `review_text?`, `add_images[]?`, `remove_images[]?` (at least one) | Review | Edit review text and/or images (paths). Each added path must be a file already uploaded to the reviewer's folder `users/<user_id>/`, else `422`. Removing only takes an image off the review; the file stays in Storage. |
| `/review/like-counter` | `review_id`, `like_flag` (1 like, 0 dislike) | `{review_id, like_count, dislike_count}` | Add a like or dislike. |

Review: `review_id, review_alphanumeric_id, dish_id, dish_name, kitchen_id, order_id, user_id, user_name, rating, review_text, images` (Image[]) `, anonymous_flag, review_time, last_edited_time, like_count, dislike_count`

## Media
| Endpoint | Input | Output | Description |
|---|---|---|---|
| `/media/upload-url` | `kind` (`"review"`), `user_id`, `file_names[]` (1-10) | `{uploads[]}` | A new path and signed upload URL per file, in that user's folder. `404` unknown user, `422` file type not allowed. |

Upload: `file_name, path, upload_url` (same order as `file_names`; only the extension of the name is kept)
