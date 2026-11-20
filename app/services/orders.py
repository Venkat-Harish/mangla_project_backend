"""Orders: a user's orders (all, from one kitchen, from one society), one order's details, and
reviewing an order.

Audited in orders_audit: ordersUserAll, ordersUserKitchen, ordersUserSociety, ordersDetails,
ordersReview.
"""

import logging
import uuid
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ConflictError, InvalidInputError, NotFoundError
from app.schemas.orders import OrderListItem, OrderOut
from app.schemas.reviews import ReviewOut
from app.services import reviews
from app.services.ratings import record_rating_change
from app.steps import audit_step
from packages.database import Dish, Kitchen, Order, Review, User

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


def review(
    session: Session,
    order_id: uuid.UUID,
    rating: Decimal,
    description: str | None,
    images: list[str],
    anonymous_flag: bool,
) -> ReviewOut:
    """Save the order's review: the order's user reviews the order's dish, once per order.

    404 unknown order, 409 already reviewed, 422 order status not in review.allowed_order_statuses
    or an image not uploaded to the user's folder. On success the review is inserted,
    orders.review_id points at it and the dish's average_ratings totals count it, all in one
    transaction.

    Locks are taken in this order (keep it in any future review delete / re-rate code, so two
    requests can't deadlock): the orders row (FOR UPDATE), the all_reviews insert, then the
    dish's average_ratings row (record_rating_change). Storage is called before any lock.
    """
    images = list(dict.fromkeys(images))  # duplicates dropped, order kept
    with audit_step("ordersReview", order_id=order_id, rating=rating,
                    text_given=description is not None, images=images,
                    anonymous_flag=anonymous_flag) as step:
        found = session.execute(
            select(Order.user_id, Order.order_status, Order.review_id)
            .where(Order.order_id == order_id)
        ).first()
        if found is None:
            raise NotFoundError("Order", order_id)
        _check_reviewable(order_id, found.order_status, found.review_id)
        if images:
            reviews.check_uploaded(found.user_id, images, "images")  # Storage: before the lock

        # populate_existing: re-read the locked row, never a copy this session already holds
        order = session.scalars(
            select(Order).where(Order.order_id == order_id)
            .with_for_update().execution_options(populate_existing=True)
        ).first()
        if order is None:
            raise NotFoundError("Order", order_id)
        earlier = session.scalar(select(Review.review_id).where(Review.order_id == order_id))
        _check_reviewable(order_id, order.order_status, order.review_id or earlier)
        if order.user_id != found.user_id:  # the images were checked against the old user
            raise ConflictError(f"Order {order_id} changed while saving the review, try again")

        new = Review(dish_id=order.dish_id, order_id=order_id, user_id=order.user_id,
                     rating=rating, review_text=description, images=images,
                     anonymous_flag=anonymous_flag)
        session.add(new)
        session.flush()  # insert the review before orders.review_id points at it
        review_id, dish_id = new.review_id, order.dish_id
        order.review_id = review_id
        totals = record_rating_change(session, dish_id, None, rating)
        session.commit()
        logger.info("Order %s reviewed: review %s, %s stars", order_id, review_id, rating)
        step.done(f"review {review_id} saved; dish {dish_id} now has "
                  f"{totals.total_reviews_count} reviews, average {totals.average_rating}")
        return reviews.review_out(session, review_id, hide_anonymous=True)


def _check_reviewable(order_id: uuid.UUID, status: str | None, review_id: uuid.UUID | None) -> None:
    """409 if the order already has a review, 422 if its status doesn't allow one."""
    if review_id is not None:
        raise ConflictError(f"Order {order_id} is already reviewed (review {review_id})")
    allowed = get_settings().review_allowed_order_statuses
    if (status or "").strip().casefold() not in allowed:
        raise InvalidInputError(
            f"Order {order_id} can't be reviewed while its status is {status!r}; "
            f"allowed: {', '.join(sorted(allowed)) or 'none'}")
