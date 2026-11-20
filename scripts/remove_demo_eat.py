"""Remove the demo data that scripts/seed_demo_eat.py adds (run before going to production).

Run from mangla_backend/:  python -m scripts.remove_demo_eat [--dry-run]

What it does:
- Demo buyer (phone +910000000001): deletes every review they wrote or that is on one of
  their orders (taking the ratings back out of average_ratings), every one of their orders
  (the 4 demo-seed-* ones and any placed from the demo frontend), then the user row.
- Dishes: the 6 dishes the seed opened go back to active_order_flag 0 with order_close_time,
  pickup_time and portions_count NULL, but only in kitchens still in the demo society.
- Societies: every kitchen and user with society_id = DEMO_SOCIETY_ID gets society_id NULL.

Not touched: the pilot kitchens, cooks and dishes themselves; audit tables (they hold request
logs, not user rows, and roll off by themselves); files in Storage (review photos uploaded
from the demo frontend are listed so they can be deleted by hand).

Safe to re-run (a second run finds nothing). One transaction; --dry-run prints what would
change and rolls back.
"""

import argparse

from sqlalchemy import delete, or_, select, update

from packages.database import AverageRating, Dish, Kitchen, Order, Review, User
from scripts.seed_demo_eat import (
    DEMO_PHONE, DEMO_SOCIETY_ID, DISH_PLAN, find_pilot_kitchens, run,
)


def remove_buyer(session, stats):
    user = session.scalar(select(User).where(User.phone_number == DEMO_PHONE))
    if user is None:
        print(f"demo buyer {DEMO_PHONE} not found")
        return
    owns_kitchen = session.scalar(select(Kitchen.kitchen_id).where(or_(
        Kitchen.user_id1 == user.user_id, Kitchen.user_id2 == user.user_id,
        Kitchen.user_id3 == user.user_id)).limit(1))
    if user.kitchen_flag or user.kitchen_id is not None or owns_kitchen is not None:
        raise RuntimeError(f"{DEMO_PHONE} belongs to a cook ({user.user_name}); not deleting it")

    order_ids = select(Order.order_id).where(Order.user_id == user.user_id)
    reviews = list(session.scalars(select(Review).where(
        or_(Review.user_id == user.user_id, Review.order_id.in_(order_ids)))))
    for review in reviews:
        # Same change as app/services/ratings.record_rating_change(dish, rating, None)
        session.execute(
            update(AverageRating).where(AverageRating.dish_id == review.dish_id)
            .values(total_reviews_count=AverageRating.total_reviews_count - 1,
                    total_stars=AverageRating.total_stars - review.rating)
            .execution_options(synchronize_session=False)
        )
        for path in review.images or []:
            print(f"left in Storage (reviews_photos_and_videos): {path}")
            stats["review_files_left_in_storage"] += 1
    review_ids = [r.review_id for r in reviews]
    if review_ids:
        # orders.review_id -> all_reviews has no ON DELETE action: clear it first
        session.execute(update(Order).where(Order.review_id.in_(review_ids))
                        .values(review_id=None).execution_options(synchronize_session=False))
        stats["reviews_deleted"] = session.execute(
            delete(Review).where(Review.review_id.in_(review_ids))
            .execution_options(synchronize_session=False)).rowcount
    stats["orders_deleted"] = session.execute(
        delete(Order).where(Order.user_id == user.user_id)
        .execution_options(synchronize_session=False)).rowcount
    print(f"deleting demo user_id {user.user_id}")
    session.delete(user)
    session.flush()
    stats["buyer_deleted"] = 1


def close_demo_dishes(session, stats):
    kitchens = find_pilot_kitchens(session)
    for i, count, *_ in DISH_PLAN:
        if i >= len(kitchens):
            continue
        kitchen = kitchens[i]
        if kitchen.society_id != DEMO_SOCIETY_ID:
            print(f"{kitchen.kitchen_name} is not in the demo society; its dishes left as is")
            continue
        dishes = session.scalars(
            select(Dish).where(Dish.kitchen_id == kitchen.kitchen_id)
            .order_by(Dish.dish_name).limit(count))
        for dish in dishes:
            if (dish.active_order_flag, dish.order_close_time, dish.pickup_time,
                    dish.portions_count) != (0, None, None, None):
                dish.active_order_flag = 0
                dish.order_close_time = None
                dish.pickup_time = None
                dish.portions_count = None
                stats["dishes_closed"] += 1


def clear_societies(session, stats):
    stats["kitchens_society_cleared"] = session.execute(
        update(Kitchen).where(Kitchen.society_id == DEMO_SOCIETY_ID).values(society_id=None)
        .execution_options(synchronize_session=False)).rowcount
    stats["users_society_cleared"] = session.execute(
        update(User).where(User.society_id == DEMO_SOCIETY_ID).values(society_id=None)
        .execution_options(synchronize_session=False)).rowcount


def remove(session):
    stats = dict.fromkeys(["reviews_deleted", "orders_deleted", "buyer_deleted", "dishes_closed",
                           "kitchens_society_cleared", "users_society_cleared",
                           "review_files_left_in_storage"], 0)
    remove_buyer(session, stats)
    close_demo_dishes(session, stats)  # before clear_societies: it checks the demo society
    session.flush()
    clear_societies(session, stats)
    print(", ".join(f"{key.replace('_', ' ')}: {n}" for key, n in stats.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="show what changes, then roll back")
    args = parser.parse_args()
    run(remove, args.dry_run)


if __name__ == "__main__":
    main()
