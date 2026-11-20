"""Load demo data so the EAT-mode screens have something to show.

Run from mangla_backend/:  python -m scripts.seed_demo_eat [--dry-run]
Undo it before going to production:  python -m scripts.remove_demo_eat

Needs the pilot kitchens first (python -m scripts.seed_pilot_kitchens). What it does:
- Upserts a demo buyer (phone +910000000001) in the demo society DEMO_SOCIETY_ID.
- Puts the pilot kitchens in the demo society, but only where society_id is NULL or already
  the demo society; a kitchen in a real society is left alone (its dishes too).
- Opens 6 dishes (kitchens sorted by name, dishes sorted by name): the first 2 dishes of the
  first 2 kitchens go live (flag 1), the first 2 of the 3rd kitchen go preorder (flag 2).
  Times are relative to when the script runs, so re-run it to refresh them.
- Upserts 4 orders for the demo buyer, keyed by payment_id demo-seed-1 .. demo-seed-4.
  An order that has been reviewed (review_id set) is never modified.

Safe to re-run. Everything runs in one transaction; --dry-run does all of it, prints the
stats and rolls back.
"""

import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from packages.database import Dish, Kitchen, Order, SessionLocal, User

SEED_FILE = Path(__file__).resolve().parents[1] / "seed" / "pilot_kitchens.json"

DEMO_SOCIETY_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "demo-society.mangla")
DEMO_PHONE = "+910000000001"
DEMO_PAYMENT_PREFIX = "demo-seed-"

# (kitchen index, number of dishes, active_order_flag, close in, pickup in, portions)
DISH_PLAN = [
    (0, 2, 1, timedelta(hours=3), timedelta(hours=1), 10),
    (1, 2, 1, timedelta(hours=3), timedelta(hours=1), 10),
    (2, 2, 2, timedelta(hours=20), timedelta(hours=26), 8),
]

# (payment_id suffix, kitchen index, dish index, status, ordered this long ago, portions)
ORDER_PLAN = [
    (1, 0, 0, "delivered", timedelta(days=2), 1),
    (2, 1, 0, "delivered", timedelta(days=5), 2),
    (3, 0, 1, "accepted", timedelta(minutes=20), 1),
    (4, 1, 1, "ready", timedelta(minutes=40), 2),
]


def run(work, dry_run):
    """Run work(session) in one transaction; commit, or roll back for a dry run."""
    session = SessionLocal()
    try:
        result = work(session)
        if dry_run:
            session.rollback()
            print("Dry run: rolled back, nothing was saved.")
        else:
            session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def find_pilot_kitchens(session):
    """The pilot kitchens that exist in the database, matched by (name, main owner phone)
    like seed_pilot_kitchens.py, sorted by name."""
    found = []
    for k in json.loads(SEED_FILE.read_text(encoding="utf-8")):
        kitchen = session.scalar(
            select(Kitchen).join(User, Kitchen.user_id1 == User.user_id)
            .where(Kitchen.kitchen_name == k["name"], User.phone_number == k["phones"][0])
        )
        if kitchen is None:
            print(f"warning: pilot kitchen {k['name']!r} not found, skipped")
        else:
            found.append(kitchen)
    return sorted(found, key=lambda kitchen: kitchen.kitchen_name)


def demo_dishes(session, kitchens):
    """{kitchen index: that kitchen's dishes sorted by name} for the kitchens the plans use."""
    needed = max(i for i, *_ in DISH_PLAN) + 1
    if len(kitchens) < needed:
        raise RuntimeError(f"need {needed} pilot kitchens, found {len(kitchens)}; "
                           "run python -m scripts.seed_pilot_kitchens first")
    dishes = {}
    for i, _, *_ in DISH_PLAN:
        dishes[i] = list(session.scalars(
            select(Dish).where(Dish.kitchen_id == kitchens[i].kitchen_id).order_by(Dish.dish_name)
        ))
    for i, count, *_ in DISH_PLAN:
        if len(dishes[i]) < count:
            raise RuntimeError(f"{kitchens[i].kitchen_name} has {len(dishes[i])} dishes, "
                               f"need {count}")
    return dishes


def upsert_buyer(session, stats):
    user = session.scalar(select(User).where(User.phone_number == DEMO_PHONE))
    if user is None:
        user = User(phone_number=DEMO_PHONE, user_name="Demo Buyer")
        session.add(user)
        stats["buyer_inserted"] += 1
    else:
        if user.kitchen_flag or user.kitchen_id is not None:
            raise RuntimeError(f"{DEMO_PHONE} belongs to a cook ({user.user_name}); not touching it")
        stats["buyer_updated"] += 1
    user.user_name = "Demo Buyer"
    user.society_id = DEMO_SOCIETY_ID
    user.block_number = "D"
    user.flat_number = "D-704"
    user.kitchen_flag = False
    session.flush()  # user_id from the database
    return user


def set_kitchen_societies(kitchens, stats):
    for kitchen in kitchens:
        if kitchen.society_id is None:
            kitchen.society_id = DEMO_SOCIETY_ID
            stats["kitchens_moved_to_demo"] += 1
        elif kitchen.society_id == DEMO_SOCIETY_ID:
            stats["kitchens_already_demo"] += 1
        else:
            print(f"warning: {kitchen.kitchen_name} is in society {kitchen.society_id}; left as is")
            stats["kitchens_in_real_society"] += 1


def open_dishes(kitchens, dishes, now, stats):
    for i, count, flag, close_in, pickup_in, portions in DISH_PLAN:
        if kitchens[i].society_id != DEMO_SOCIETY_ID:
            print(f"warning: {kitchens[i].kitchen_name} is not in the demo society; "
                  "its dishes were not opened")
            continue
        for dish in dishes[i][:count]:
            dish.active_order_flag = flag
            dish.order_close_time = now + close_in
            dish.pickup_time = now + pickup_in
            dish.portions_count = portions
            stats["dishes_opened"] += 1


def upsert_orders(session, user, kitchens, dishes, now, stats):
    for n, ki, di, status, ago, portions in ORDER_PLAN:
        payment_id = f"{DEMO_PAYMENT_PREFIX}{n}"
        dish = dishes[ki][di]
        order = session.scalar(
            select(Order).where(Order.user_id == user.user_id, Order.payment_id == payment_id)
        )
        if order is None:
            order = Order(user_id=user.user_id, payment_id=payment_id)
            session.add(order)
            stats["orders_inserted"] += 1
        elif order.review_id is not None:
            stats["orders_kept_reviewed"] += 1
            continue
        else:
            stats["orders_updated"] += 1
        order.kitchen_id = kitchens[ki].kitchen_id
        order.dish_id = dish.dish_id
        order.portion_count = portions
        order.order_status = status
        order.order_time = now - ago
        order.refund_flag = False


def seed(session):
    stats = dict.fromkeys(["buyer_inserted", "buyer_updated", "kitchens_moved_to_demo",
                           "kitchens_already_demo", "kitchens_in_real_society", "dishes_opened",
                           "orders_inserted", "orders_updated", "orders_kept_reviewed"], 0)
    now = datetime.now(timezone.utc)
    kitchens = find_pilot_kitchens(session)
    dishes = demo_dishes(session, kitchens)
    user = upsert_buyer(session, stats)
    set_kitchen_societies(kitchens, stats)
    open_dishes(kitchens, dishes, now, stats)
    upsert_orders(session, user, kitchens, dishes, now, stats)
    session.flush()
    print(", ".join(f"{key.replace('_', ' ')}: {n}" for key, n in stats.items()))
    return user.user_id


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="do everything, then roll back")
    args = parser.parse_args()
    user_id = run(seed, args.dry_run)
    print(f"demo user_id:    {user_id}" + ("  (dry run: not saved)" if args.dry_run else ""))
    print(f"DEMO_SOCIETY_ID: {DEMO_SOCIETY_ID}")
    print(f"Frontend: VITE_DEMO_USER_ID={user_id}")


if __name__ == "__main__":
    main()
