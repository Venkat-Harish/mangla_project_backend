"""Orders: a user's orders (all, from one kitchen, from one society) and one order's details.

Audited in orders_audit: ordersUserAll, ordersUserKitchen, ordersUserSociety, ordersDetails.
"""

import logging
import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.schemas.orders import OrderListItem, OrderOut
from app.steps import audit_step
from packages.database import Dish, Kitchen, Order, User

logger = logging.getLogger(__name__)


def _user_orders(user_id: uuid.UUID) -> Select:
    """The user's orders with kitchen and dish names, newest first."""
    return (
        select(*Order.__table__.columns, Kitchen.kitchen_name, Dish.dish_name)
        .join(Kitchen, Kitchen.kitchen_id == Order.kitchen_id)
        .join(Dish, Dish.dish_id == Order.dish_id)
        .where(Order.user_id == user_id)
        .order_by(Order.order_time.desc(), Order.order_id)
    )


def _run(session: Session, statement: Select) -> list[OrderListItem]:
    return [OrderListItem.model_validate(row) for row in session.execute(statement).mappings()]


def user_all(session: Session, user_id: uuid.UUID) -> list[OrderListItem]:
    with audit_step("ordersUserAll", user_id=user_id) as step:
        orders = _run(session, _user_orders(user_id))
        step.done(f"{len(orders)} orders")
        return orders


def user_kitchen(session: Session, user_id: uuid.UUID, kitchen_id: uuid.UUID) -> list[OrderListItem]:
    with audit_step("ordersUserKitchen", user_id=user_id, kitchen_id=kitchen_id) as step:
        orders = _run(session, _user_orders(user_id).where(Order.kitchen_id == kitchen_id))
        step.done(f"{len(orders)} orders")
        return orders


def user_society(
    session: Session, user_id: uuid.UUID, society_id: uuid.UUID | None
) -> list[OrderListItem]:
    """Orders from kitchens in society_id; None means the user's own society (none set: empty)."""
    with audit_step("ordersUserSociety", user_id=user_id, society_id=society_id) as step:
        if society_id is None:
            user = session.get(User, user_id)
            if user is None:
                raise NotFoundError("User", user_id)
            society_id = user.society_id
            if society_id is None:
                logger.info("User %s has no society set; no society orders to return", user_id)
                step.done("user has no society: 0 orders")
                return []
            logger.info("No society_id given; using the user's society %s", society_id)
        orders = _run(session, _user_orders(user_id).where(Kitchen.society_id == society_id))
        step.done(f"{len(orders)} orders from society {society_id}")
        return orders


def details(session: Session, order_id: uuid.UUID) -> OrderOut:
    with audit_step("ordersDetails", order_id=order_id) as step:
        order = session.get(Order, order_id)
        if order is None:
            raise NotFoundError("Order", order_id)
        step.done(f"{order.order_alphanumeric_id} status={order.order_status}")
        return OrderOut.model_validate(order)
