"""Cart: the items in users.cart with each dish's current details. Logged, not audited."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.schemas.cart import CartItemOut, CartOut
from app.steps import log_step
from packages.database import Dish, Kitchen, User

logger = logging.getLogger(__name__)


def _dish_uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def user_cart(session: Session, user_id: uuid.UUID) -> CartOut:
    """users.cart is a JSON list of {"dish_id", "portion_count"}; entries keep their order.
    An entry whose dish is gone (or whose dish_id is not a UUID) comes back with available=false."""
    with log_step("cartUser", user_id=user_id) as step:
        user = session.get(User, user_id)
        if user is None:
            raise NotFoundError("User", user_id)
        raw = user.cart if isinstance(user.cart, list) else []
        entries = [e for e in raw if isinstance(e, dict)]
        if len(entries) != len(raw):
            logger.warning("User %s cart has %d entries that are not objects; skipped",
                           user_id, len(raw) - len(entries))

        dish_ids = {d for d in (_dish_uuid(e.get("dish_id")) for e in entries) if d is not None}
        dishes = {}
        if dish_ids:
            rows = session.execute(
                select(Dish, Kitchen.kitchen_name)
                .join(Kitchen, Kitchen.kitchen_id == Dish.kitchen_id)
                .where(Dish.dish_id.in_(dish_ids))
            ).all()
            dishes = {dish.dish_id: (dish, kitchen_name) for dish, kitchen_name in rows}

        items = []
        for entry in entries:
            portion_count = entry.get("portion_count")
            item = CartItemOut(
                dish_id=str(entry.get("dish_id")),
                portion_count=portion_count if isinstance(portion_count, int) else None,
                available=False,
            )
            found = dishes.get(_dish_uuid(entry.get("dish_id")))
            if found is not None:
                dish, kitchen_name = found
                item = item.model_copy(update={
                    "available": True,
                    "dish_name": dish.dish_name,
                    "dish_price": float(dish.dish_price),
                    "images": dish.images,
                    "active_order_flag": dish.active_order_flag,
                    "kitchen_id": dish.kitchen_id,
                    "kitchen_name": kitchen_name,
                })
            else:
                logger.warning("User %s cart item %s: dish not found", user_id, item.dish_id)
            items.append(item)
        unavailable = sum(not i.available for i in items)
        step.done(f"{len(items)} cart items ({unavailable} unavailable)")
        return CartOut(user_id=user_id, items=items)
