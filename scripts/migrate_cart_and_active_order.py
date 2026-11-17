"""Add users.cart and turn all_dishes.active_order_flag into 0/1/2.

- users.cart: JSONB list of {"dish_id": "<uuid>", "portion_count": n}, default [].
- all_dishes.active_order_flag: boolean -> smallint (0 = off, 1 = live, 2 = preorder);
  existing false becomes 0 and true becomes 1. Check ck_all_dishes_active_order_flag_range.

Run from mangla_backend/:  python -m scripts.migrate_cart_and_active_order
Safe to re-run: each change is skipped when it is already in place. One transaction.
"""

from sqlalchemy import text

from packages.database import engine

ADD_CART = """
ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS cart JSONB DEFAULT '[]'::jsonb NOT NULL
"""

FLAG_TYPE = """
SELECT data_type FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'all_dishes' AND column_name = 'active_order_flag'
"""

CONVERT_FLAG = [
    "ALTER TABLE public.all_dishes ALTER COLUMN active_order_flag DROP DEFAULT",
    "ALTER TABLE public.all_dishes ALTER COLUMN active_order_flag TYPE SMALLINT "
    "USING (CASE WHEN active_order_flag THEN 1 ELSE 0 END)",
    "ALTER TABLE public.all_dishes ALTER COLUMN active_order_flag SET DEFAULT 0",
]

HAS_CHECK = """
SELECT 1 FROM pg_constraint
WHERE conname = 'ck_all_dishes_active_order_flag_range' AND conrelid = 'public.all_dishes'::regclass
"""

ADD_CHECK = """
ALTER TABLE public.all_dishes ADD CONSTRAINT ck_all_dishes_active_order_flag_range
    CHECK (active_order_flag IN (0, 1, 2))
"""


def main():
    with engine.begin() as conn:
        conn.execute(text(ADD_CART))
        print("users.cart: present")

        flag_type = conn.execute(text(FLAG_TYPE)).scalar_one()
        if flag_type == "boolean":
            for statement in CONVERT_FLAG:
                conn.execute(text(statement))
            print("all_dishes.active_order_flag: converted boolean -> smallint")
        else:
            print(f"all_dishes.active_order_flag: already {flag_type}")

        if conn.execute(text(HAS_CHECK)).first() is None:
            conn.execute(text(ADD_CHECK))
            print("ck_all_dishes_active_order_flag_range: added")
        else:
            print("ck_all_dishes_active_order_flag_range: already present")


if __name__ == "__main__":
    main()
