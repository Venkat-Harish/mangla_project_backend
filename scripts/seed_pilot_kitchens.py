"""Load the pilot cooks, their kitchens and menus into Supabase.

Data: seed/pilot_kitchens.json, exported from the prototype's src/data/cooks.js.
Run from mangla_backend/:  python -m scripts.seed_pilot_kitchens

Safe to re-run: users are matched by phone number, kitchens by (name, main owner),
dishes by (kitchen, name). Existing rows are updated, nothing is duplicated.
Everything runs in one transaction and rolls back on any error.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from packages.database import Dish, Kitchen, User, get_session

SEED_FILE = Path(__file__).resolve().parents[1] / "seed" / "pilot_kitchens.json"


def upsert_user(session, phone, name, stats):
    user = session.scalar(select(User).where(User.phone_number == phone))
    if user is None:
        user = User(phone_number=phone, user_name=name, kitchen_flag=True,
                    kitchen_register_time=datetime.now(timezone.utc))
        session.add(user)
        session.flush()  # get user_id from the database
        stats["users_inserted"] += 1
    else:
        user.user_name = name
        user.kitchen_flag = True
        stats["users_updated"] += 1
    return user


def upsert_kitchen(session, name, owners, stats):
    main, *others = owners
    kitchen = session.scalar(
        select(Kitchen).where(Kitchen.kitchen_name == name, Kitchen.user_id1 == main.user_id)
    )
    if kitchen is None:
        kitchen = Kitchen(kitchen_name=name, user_id1=main.user_id)
        session.add(kitchen)
        stats["kitchens_inserted"] += 1
    else:
        stats["kitchens_updated"] += 1
    kitchen.user_id2 = others[0].user_id if len(others) > 0 else None
    kitchen.user_id3 = others[1].user_id if len(others) > 1 else None
    session.flush()  # kitchen_id + trigger-generated KIT-… id
    for user in owners:
        user.kitchen_id = kitchen.kitchen_id
    return kitchen


def upsert_dishes(session, kitchen, menu, stats):
    existing = {
        d.dish_name: d
        for d in session.scalars(select(Dish).where(Dish.kitchen_id == kitchen.kitchen_id))
    }
    for item in menu:
        price = Decimal(str(item["price"]))
        dish = existing.get(item["name"])
        if dish is None:
            session.add(Dish(kitchen_id=kitchen.kitchen_id, dish_name=item["name"],
                             dish_price=price, description=item["desc"], images=[]))
            stats["dishes_inserted"] += 1
        elif dish.dish_price != price or dish.description != item["desc"]:
            dish.dish_price = price
            dish.description = item["desc"]
            stats["dishes_updated"] += 1


def main():
    kitchens = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    stats = dict.fromkeys(["users_inserted", "users_updated", "kitchens_inserted",
                           "kitchens_updated", "dishes_inserted", "dishes_updated"], 0)
    with get_session() as session:
        for k in kitchens:
            if len(k["phones"]) > 3:
                raise ValueError(f"{k['name']}: all_kitchens holds at most 3 owner users")
            owners = [upsert_user(session, phone, k["owner"], stats) for phone in k["phones"]]
            kitchen = upsert_kitchen(session, k["name"], owners, stats)
            upsert_dishes(session, kitchen, k["menu"], stats)
            print(f"{kitchen.kitchen_alphanumeric_id}  {k['name']:<20} "
                  f"{len(owners)} user(s), {len(k['menu'])} dishes")
    print(", ".join(f"{key.replace('_', ' ')}: {n}" for key, n in stats.items()))


if __name__ == "__main__":
    main()
