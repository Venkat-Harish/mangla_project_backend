# Mangla Database

Postgres on Supabase (project ref `rpthhezkrrjtumyqtndz`). The connection string is read from `DATABASE_URL` in `.env`, which is git-ignored.

Tables are created one at a time. Each table is defined as a SQLAlchemy ORM model in `packages/database/models/<table>.py`, created in Supabase from that model, and documented below.

Code layout (`packages/database/`):
- `db.py`: the single engine, `SessionLocal`, `get_session()` and `run_query(sql, params)`
- `base.py`: the `Base` class all models inherit from
- `ddl.py`: database-level SQL create_all can't express (alphanumeric-ID function and trigger, review edit-time trigger, RLS), hooked in with SQLAlchemy DDL events
- `models/`: one ORM model file per table (`users.py`, `all_kitchens.py`, `all_dishes.py`, `orders.py`, `all_reviews.py`)

Import everything from the package: `from packages.database import get_session, User, Review`.

To create any new tables: `Base.metadata.create_all(engine)`. It skips tables that already exist.

Install deps: `pip install -r requirements.txt`

## Tables

| # | Table | Purpose | Created |
|---|-------|---------|---------|
| 1 | [users](#users) | App users, their society/flat and kitchen details | 2026-11-16 |
| 2 | [all_kitchens](#all_kitchens) | Home kitchens, their society and up to 3 owner users | 2026-11-16 |
| 3 | [all_dishes](#all_dishes) | Dishes each kitchen offers, with price, images and timings | 2026-11-16 |
| 4 | [orders](#orders) | Orders placed by users for a dish from a kitchen | 2026-11-16 |
| 5 | [all_reviews](#all_reviews) | Users' reviews of dishes, tied to an order | 2026-11-16 |

## Auto-generated alphanumeric IDs

`all_kitchens.kitchen_alphanumeric_id` (`KIT-XXXXXXXX`), `orders.order_alphanumeric_id` (`ORD-XXXXXXXX`) and `all_reviews.review_alphanumeric_id` (`REV-XXXXXXXX`) are filled in by the database on insert. Leave them out when creating a row; the ORM reads the value back automatically.

- `public.generate_alnum_code(prefix, len = 8)`: prefix + 8 random characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (no 0/O/1/I), about 1.1 trillion combinations. The randomness comes from `gen_random_uuid()`.
- `public.set_alnum_id()`: BEFORE INSERT trigger function with arguments (column, prefix). If the column is empty, it generates a code and retries until the code isn't already in the table. The column's UNIQUE constraint is a final safety net.
- Triggers: `all_kitchens_set_alnum_id`, `orders_set_alnum_id`, `all_reviews_set_alnum_id`.
- Full SQL is in `packages/database/ddl.py`.

---

## users

**Purpose:** App users, the society/block/flat they live in, and their kitchen details if they run one.
**Model:** `packages/database/models/users.py` (`User`)
**Created:** 2026-11-16

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| user_id | uuid | no | gen_random_uuid() | Primary key |
| phone_number | text | no | | Unique |
| user_name | text | no | | |
| society_id | uuid | yes | | FK to societies once that table exists |
| block_number | text | yes | | Text so values like `A-12` work |
| flat_number | text | yes | | |
| kitchen_flag | boolean | no | false | True if the user runs a kitchen |
| kitchen_id | uuid | yes | | FK → all_kitchens.kitchen_id |
| pinned_kitchen | jsonb | yes | | |
| kitchen_register_time | timestamptz | yes | | ISO 8601 with time zone |
| user_register_time | timestamptz | no | now() | ISO 8601 with time zone |

**Keys / foreign keys:** PK `users_pkey` (user_id); unique `users_phone_number_key` (phone_number); FK `users_kitchen_id_fkey` (kitchen_id → all_kitchens), added 2026-11-16 with `ALTER TABLE` because users and all_kitchens reference each other.
**Indexes:** the ones created by the PK and the unique constraint.
**Row Level Security:** enabled, no policies. The backend connects as `postgres` and bypasses RLS; Supabase's public REST API (anon key) can't read or write this table.

```sql
CREATE TABLE users (
	user_id UUID DEFAULT gen_random_uuid() NOT NULL,
	phone_number TEXT NOT NULL,
	user_name TEXT NOT NULL,
	society_id UUID,
	block_number TEXT,
	flat_number TEXT,
	kitchen_flag BOOLEAN DEFAULT false NOT NULL,
	kitchen_id UUID,
	pinned_kitchen JSONB,
	kitchen_register_time TIMESTAMP WITH TIME ZONE,
	user_register_time TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (user_id),
	UNIQUE (phone_number)
);
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
-- added 2026-11-16, once all_kitchens existed
ALTER TABLE public.users ADD CONSTRAINT users_kitchen_id_fkey
	FOREIGN KEY (kitchen_id) REFERENCES public.all_kitchens (kitchen_id);
```

---

## all_kitchens

**Purpose:** Home kitchens, the society they're in, and up to three users who run them.
**Model:** `packages/database/models/all_kitchens.py` (`Kitchen`)
**Created:** 2026-11-16

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| kitchen_id | uuid | no | gen_random_uuid() | Primary key |
| kitchen_name | text | no | | |
| society_id | uuid | yes | | FK to societies once that table exists |
| user_id1 | uuid | no | | FK → users (main owner) |
| user_id2 | uuid | yes | | FK → users |
| user_id3 | uuid | yes | | FK → users |
| kitchen_alphanumeric_id | text | no | trigger | Unique, auto `KIT-XXXXXXXX` |

**Keys / foreign keys:** PK `all_kitchens_pkey`; unique `all_kitchens_kitchen_alphanumeric_id_key`; FKs `all_kitchens_user_id1_fkey`, `_user_id2_fkey` and `_user_id3_fkey` → users.
**Indexes:** `ix_all_kitchens_society_id_kitchen_id` (society_id, kitchen_id), which makes looking up a society's kitchens fast.
**Trigger:** `all_kitchens_set_alnum_id`. **Row Level Security:** enabled, no policies.

```sql
CREATE TABLE all_kitchens (
	kitchen_id UUID DEFAULT gen_random_uuid() NOT NULL,
	kitchen_name TEXT NOT NULL,
	society_id UUID,
	user_id1 UUID NOT NULL,
	user_id2 UUID,
	user_id3 UUID,
	kitchen_alphanumeric_id TEXT NOT NULL,
	PRIMARY KEY (kitchen_id),
	FOREIGN KEY(user_id1) REFERENCES users (user_id),
	FOREIGN KEY(user_id2) REFERENCES users (user_id),
	FOREIGN KEY(user_id3) REFERENCES users (user_id),
	UNIQUE (kitchen_alphanumeric_id)
);
CREATE INDEX ix_all_kitchens_society_id_kitchen_id ON all_kitchens (society_id, kitchen_id);
CREATE TRIGGER all_kitchens_set_alnum_id BEFORE INSERT ON public.all_kitchens
	FOR EACH ROW EXECUTE FUNCTION public.set_alnum_id('kitchen_alphanumeric_id', 'KIT-');
ALTER TABLE public.all_kitchens ENABLE ROW LEVEL SECURITY;
```

---

## all_dishes

**Purpose:** Dishes each kitchen offers, with price, images, order window and pickup time.
**Model:** `packages/database/models/all_dishes.py` (`Dish`)
**Created:** 2026-11-16

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| dish_id | uuid | no | gen_random_uuid() | Primary key |
| kitchen_id | uuid | no | | FK → all_kitchens |
| dish_name | text | no | | |
| dish_price | numeric(10,2) | no | | ≥ 0; exact decimal (Python `Decimal`) |
| images | jsonb | no | `'[]'` | List of Supabase Storage URLs |
| description | text | yes | | |
| active_order_flag | boolean | no | false | |
| order_close_time | timestamptz | yes | | ISO 8601 with time zone |
| pickup_time | timestamptz | yes | | ISO 8601 with time zone |
| portions_count | integer | yes | | ≥ 0 |

**Keys / foreign keys:** PK `all_dishes_pkey`; FK `all_dishes_kitchen_id_fkey` → all_kitchens; checks `ck_all_dishes_dish_price_nonnegative`, `ck_all_dishes_portions_count_nonnegative`.
**Indexes:** `ix_all_dishes_kitchen_id_dish_id` (kitchen_id, dish_id), which makes looking up a kitchen's dishes fast.
**Row Level Security:** enabled, no policies.

```sql
CREATE TABLE all_dishes (
	dish_id UUID DEFAULT gen_random_uuid() NOT NULL,
	kitchen_id UUID NOT NULL,
	dish_name TEXT NOT NULL,
	dish_price NUMERIC(10, 2) NOT NULL,
	images JSONB DEFAULT '[]'::jsonb NOT NULL,
	description TEXT,
	active_order_flag BOOLEAN DEFAULT false NOT NULL,
	order_close_time TIMESTAMP WITH TIME ZONE,
	pickup_time TIMESTAMP WITH TIME ZONE,
	portions_count INTEGER,
	PRIMARY KEY (dish_id),
	CONSTRAINT ck_all_dishes_dish_price_nonnegative CHECK (dish_price >= 0),
	CONSTRAINT ck_all_dishes_portions_count_nonnegative CHECK (portions_count >= 0),
	FOREIGN KEY(kitchen_id) REFERENCES all_kitchens (kitchen_id)
);
CREATE INDEX ix_all_dishes_kitchen_id_dish_id ON all_dishes (kitchen_id, dish_id);
ALTER TABLE public.all_dishes ENABLE ROW LEVEL SECURITY;
```

---

## orders

**Purpose:** An order a user places for a dish from a kitchen.
**Model:** `packages/database/models/orders.py` (`Order`)
**Created:** 2026-11-16

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| order_id | uuid | no | gen_random_uuid() | Primary key |
| order_alphanumeric_id | text | no | trigger | Unique, auto `ORD-XXXXXXXX` |
| kitchen_id | uuid | no | | FK → all_kitchens |
| dish_id | uuid | no | | FK → all_dishes |
| user_id | uuid | no | | FK → users |
| portion_count | integer | no | | > 0 |
| order_time | timestamptz | no | now() | ISO 8601 with time zone |
| order_status | text | no | | Free text |
| payment_id | text | yes | | Payment gateway ID (e.g. `pay_...`) |
| refund_flag | boolean | no | false | |

**Keys / foreign keys:** PK `orders_pkey`; unique `orders_order_alphanumeric_id_key`; FKs `orders_kitchen_id_fkey`, `orders_dish_id_fkey`, `orders_user_id_fkey`; check `ck_orders_portion_count_positive`.
**Indexes:** `ix_orders_user_id_order_id` (user_id, order_id). user_id comes first so "all orders for a user" is fast; order_id alone is already indexed by the PK.
**Trigger:** `orders_set_alnum_id`. **Row Level Security:** enabled, no policies.

```sql
CREATE TABLE orders (
	order_id UUID DEFAULT gen_random_uuid() NOT NULL,
	order_alphanumeric_id TEXT NOT NULL,
	kitchen_id UUID NOT NULL,
	dish_id UUID NOT NULL,
	user_id UUID NOT NULL,
	portion_count INTEGER NOT NULL,
	order_time TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	order_status TEXT NOT NULL,
	payment_id TEXT,
	refund_flag BOOLEAN DEFAULT false NOT NULL,
	PRIMARY KEY (order_id),
	CONSTRAINT ck_orders_portion_count_positive CHECK (portion_count > 0),
	UNIQUE (order_alphanumeric_id),
	FOREIGN KEY(kitchen_id) REFERENCES all_kitchens (kitchen_id),
	FOREIGN KEY(dish_id) REFERENCES all_dishes (dish_id),
	FOREIGN KEY(user_id) REFERENCES users (user_id)
);
CREATE INDEX ix_orders_user_id_order_id ON orders (user_id, order_id);
CREATE TRIGGER orders_set_alnum_id BEFORE INSERT ON public.orders
	FOR EACH ROW EXECUTE FUNCTION public.set_alnum_id('order_alphanumeric_id', 'ORD-');
ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;
```

---

## all_reviews

**Purpose:** A user's review of a dish, tied to the order it came from. A user can review the same dish more than once.
**Model:** `packages/database/models/all_reviews.py` (`Review`)
**Created:** 2026-11-16

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| review_id | uuid | no | gen_random_uuid() | Primary key |
| review_alphanumeric_id | text | no | trigger | Unique, auto `REV-XXXXXXXX` |
| dish_id | uuid | no | | FK → all_dishes |
| order_id | uuid | no | | FK → orders |
| user_id | uuid | no | | FK → users |
| rating | numeric(2,1) | no | | Half stars 0.5–5.0 (Python `Decimal`) |
| review_text | text | yes | | |
| images | jsonb | no | `'[]'` | List of Supabase Storage URLs |
| anonymous_flag | boolean | no | false | |
| review_time | timestamptz | no | now() | ISO 8601 with time zone |
| last_edited_time | timestamptz | yes | trigger | Set when rating/text/images/anonymous_flag change; null if never edited |
| like_count | integer | no | 0 | ≥ 0 |
| dislike_count | integer | no | 0 | ≥ 0 |

**Keys / foreign keys:** PK `all_reviews_pkey`; unique `all_reviews_review_alphanumeric_id_key`; FKs `all_reviews_dish_id_fkey`, `all_reviews_order_id_fkey`, `all_reviews_user_id_fkey`; checks `ck_all_reviews_rating_half_stars`, `ck_all_reviews_like_count_nonnegative`, `ck_all_reviews_dislike_count_nonnegative`.
**Indexes:** `ix_all_reviews_dish_id_review_id` (dish_id, review_id) and `ix_all_reviews_user_id_review_id` (user_id, review_id), which make "reviews for a dish" and "reviews by a user" fast.
**Triggers:** `all_reviews_set_alnum_id`; `all_reviews_set_last_edited` (BEFORE UPDATE, function `public.set_review_last_edited()`). Like/dislike updates don't count as edits. **Row Level Security:** enabled, no policies.

```sql
CREATE TABLE all_reviews (
	review_id UUID DEFAULT gen_random_uuid() NOT NULL,
	review_alphanumeric_id TEXT NOT NULL,
	dish_id UUID NOT NULL,
	order_id UUID NOT NULL,
	user_id UUID NOT NULL,
	rating NUMERIC(2, 1) NOT NULL,
	review_text TEXT,
	images JSONB DEFAULT '[]'::jsonb NOT NULL,
	anonymous_flag BOOLEAN DEFAULT false NOT NULL,
	review_time TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	last_edited_time TIMESTAMP WITH TIME ZONE,
	like_count INTEGER DEFAULT 0 NOT NULL,
	dislike_count INTEGER DEFAULT 0 NOT NULL,
	PRIMARY KEY (review_id),
	CONSTRAINT ck_all_reviews_rating_half_stars CHECK (rating >= 0.5 AND rating <= 5 AND rating * 2 = trunc(rating * 2)),
	CONSTRAINT ck_all_reviews_like_count_nonnegative CHECK (like_count >= 0),
	CONSTRAINT ck_all_reviews_dislike_count_nonnegative CHECK (dislike_count >= 0),
	UNIQUE (review_alphanumeric_id),
	FOREIGN KEY(dish_id) REFERENCES all_dishes (dish_id),
	FOREIGN KEY(order_id) REFERENCES orders (order_id),
	FOREIGN KEY(user_id) REFERENCES users (user_id)
);
CREATE INDEX ix_all_reviews_dish_id_review_id ON all_reviews (dish_id, review_id);
CREATE INDEX ix_all_reviews_user_id_review_id ON all_reviews (user_id, review_id);
CREATE TRIGGER all_reviews_set_alnum_id BEFORE INSERT ON public.all_reviews
	FOR EACH ROW EXECUTE FUNCTION public.set_alnum_id('review_alphanumeric_id', 'REV-');
CREATE TRIGGER all_reviews_set_last_edited BEFORE UPDATE ON public.all_reviews
	FOR EACH ROW EXECUTE FUNCTION public.set_review_last_edited();
ALTER TABLE public.all_reviews ENABLE ROW LEVEL SECURITY;
```

---

## Seed data

**Pilot kitchens** (loaded 2026-11-16): the six pilot cooks, their kitchens and menus.

- **Data:** `seed/pilot_kitchens.json`, exported from the prototype's `src/data/cooks.js` (owner, phone numbers in E.164 like `+917993753928`, menu name/description/price).
- **Script:** `scripts/seed_pilot_kitchens.py`. Run from `mangla_backend/`: `python -m scripts.seed_pilot_kitchens`
- **Loads:** 7 users (Yummy Food has a second number, linked as `user_id2`), 6 kitchens, 99 dishes. Users get `kitchen_flag = true` and `kitchen_id`; society, block and flat are NULL until known. Dishes have `images = []` and `active_order_flag = false`.
- **Re-running** is safe: users are matched by phone, kitchens by (name, main owner), dishes by (kitchen, name). Existing rows are updated, nothing is duplicated. One transaction; any error rolls everything back.
- To refresh after editing the prototype's menus, re-export the JSON from `prototype/` (Node import of `src/data/cooks.js`) and run the script again. Dishes removed from the JSON are not deleted from the table.

---

<!--
Template for each table (copy below this line):

## <table_name>

**Purpose:** ...
**Migration:** `migrations/NNN_<table_name>.sql`
**Created:** YYYY-MM-DD

| Column | Type | Nullable | Default | Notes |
|--------|------|----------|---------|-------|
| id | uuid | no | gen_random_uuid() | Primary key |

**Keys / foreign keys:** ...
**Indexes:** ...

```sql
CREATE TABLE ...
```
-->
