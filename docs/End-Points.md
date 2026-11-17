# API Endpoints

All endpoints are `POST` with a JSON body, mounted under `api.prefix` (default `/app`), e.g. `POST /app/account/user-info`.
IDs are UUIDs. `?` = optional. Errors: `404` not found, `422` invalid body (both include `request_id`).

## Account
| Endpoint | Input | Output | Description |
|---|---|---|---|
| `/account/user-info` | `user_id` | User (all user columns) | Everything stored about the user. |

## Cart
| Endpoint | Input | Output | Description |
|---|---|---|---|
| `/cart/user` | `user_id` | `{user_id, items[]}` | Items in the user's cart with current dish details. |

Cart item: `dish_id, portion_count, available, dish_name, dish_price, images, active_order_flag, kitchen_id, kitchen_name`

## Home
| Endpoint | Input | Output | Description |
|---|---|---|---|
| `/home/kitchen-society-all` | `user_id`, `society_id?` | Kitchen[] + `pinned` | Pinned kitchens first, then the rest of the society (default: user's society). |
| `/home/update-pinned` | `user_id`, `kitchen_id`, `pin?` (default `true`) | `{user_id, pinned_kitchen[]}` | Pin / unpin a kitchen. |
| `/home/kitchen-live` | `society_id` | Kitchen[] + `dishes[]` | Kitchens with a dish where `active_order_flag` is 1 or 2. |
| `/home/kitchen-preorder` | `society_id` | Kitchen[] + `dishes[]` | Kitchens with a dish where `active_order_flag` is 2. |

Kitchen: `kitchen_id, kitchen_alphanumeric_id, kitchen_name, society_id, user_id1, user_id2, user_id3`
Dish: `dish_id, dish_name, dish_price, images, description, active_order_flag, order_close_time, pickup_time, portions_count`

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
| `/review/edit` | `review_id`, `review_text?`, `add_images[]?`, `remove_images[]?` (at least one) | Review | Edit review text and/or images. |
| `/review/like-counter` | `review_id`, `like_flag` (1 like, 0 dislike) | `{review_id, like_count, dislike_count}` | Add a like or dislike. |

Review: `review_id, review_alphanumeric_id, dish_id, dish_name, kitchen_id, order_id, user_id, user_name, rating, review_text, images, anonymous_flag, review_time, last_edited_time, like_count, dislike_count`
