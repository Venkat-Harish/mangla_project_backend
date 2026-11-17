"""Add orders.review_id (the order's review; NULL = not reviewed) and allow one review per order.

- orders.review_id uuid, nullable; unique (orders_review_id_key); FK orders_review_id_fkey ->
  all_reviews.review_id with no ON DELETE action (deleting a review must clear it first).
- all_reviews.order_id unique (all_reviews_order_id_key): one review per order.
- Existing reviews are backfilled into orders.review_id.

Run from mangla_backend/:  python -m scripts.migrate_orders_review_id
Safe to re-run: each change is skipped when it is already in place. One transaction; it stops
(and changes nothing) if an order has several reviews or review_id points at another order's review.
Run it before deploying code that reads orders.review_id.
"""

from sqlalchemy import text

from packages.database import engine

HAS_CONSTRAINT = """
SELECT 1 FROM pg_constraint
WHERE conname = :name AND conrelid = CAST(:table AS regclass)
"""

ORDERS_WITH_SEVERAL_REVIEWS = """
SELECT order_id::text, count(*) AS reviews FROM public.all_reviews
GROUP BY order_id HAVING count(*) > 1 ORDER BY order_id LIMIT 20
"""

BACKFILL = """
UPDATE public.orders o SET review_id = r.review_id
FROM public.all_reviews r
WHERE r.order_id = o.order_id AND o.review_id IS NULL
"""

MISMATCHED = """
SELECT o.order_id::text, o.review_id::text FROM public.orders o
JOIN public.all_reviews r ON r.review_id = o.review_id
WHERE r.order_id <> o.order_id LIMIT 20
"""

CONSTRAINTS = [
    ("all_reviews_order_id_key", "public.all_reviews",
     "ALTER TABLE public.all_reviews ADD CONSTRAINT all_reviews_order_id_key UNIQUE (order_id)"),
    ("orders_review_id_key", "public.orders",
     "ALTER TABLE public.orders ADD CONSTRAINT orders_review_id_key UNIQUE (review_id)"),
    ("orders_review_id_fkey", "public.orders",
     "ALTER TABLE public.orders ADD CONSTRAINT orders_review_id_fkey "
     "FOREIGN KEY (review_id) REFERENCES public.all_reviews (review_id)"),
]


def _add_constraint(conn, name: str, table: str, ddl: str) -> None:
    if conn.execute(text(HAS_CONSTRAINT), {"name": name, "table": table}).first() is None:
        conn.execute(text(ddl))
        print(f"{name}: added")
    else:
        print(f"{name}: already present")


def main():
    with engine.begin() as conn:
        # Fail fast instead of queueing live traffic behind this ALTER's exclusive lock
        conn.execute(text("SET LOCAL lock_timeout = '5s'"))

        conn.execute(text("ALTER TABLE public.orders ADD COLUMN IF NOT EXISTS review_id UUID"))
        print("orders.review_id: present")

        several = conn.execute(text(ORDERS_WITH_SEVERAL_REVIEWS)).all()
        if several:
            raise SystemExit("Stopped, nothing changed: these orders have more than one review "
                             f"(order_id, count): {several}")
        _add_constraint(conn, *CONSTRAINTS[0])

        filled = conn.execute(text(BACKFILL)).rowcount
        print(f"orders.review_id backfilled from all_reviews: {filled} rows")

        mismatched = conn.execute(text(MISMATCHED)).all()
        if mismatched:
            raise SystemExit("Stopped, nothing changed: orders.review_id points at another "
                             f"order's review (order_id, review_id): {mismatched}")
        for constraint in CONSTRAINTS[1:]:
            _add_constraint(conn, *constraint)


if __name__ == "__main__":
    main()
