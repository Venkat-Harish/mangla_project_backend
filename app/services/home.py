"""Home screen: pinned + society kitchens, pin/unpin, and kitchens with live or preorder dishes.

Audited in home_audit: homeKitchenSocietyAll, homePinnedUpdate, homeKitchenLive, homeKitchenPreorder.
"""

import logging
import uuid
from collections.abc import Collection

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import NotFoundError
from app.schemas.home import ActiveDishOut, ActiveKitchenOut, HomeKitchenOut, PinnedOut
from app.steps import audit_step
from packages import storage
from packages.database import Dish, Kitchen, User

logger = logging.getLogger(__name__)

LIVE_FLAGS = (1, 2)  # all_dishes.active_order_flag: 1 = live, 2 = preorder
PREORDER_FLAGS = (2,)


def pinned_ids(raw) -> list[str]:
    """users.pinned_kitchen as a clean list of kitchen ID strings: order kept, no duplicates,
    entries that are not UUIDs dropped."""
    ids: list[str] = []
    for value in raw if isinstance(raw, list) else []:
        try:
            kitchen_id = str(uuid.UUID(str(value)))
        except ValueError:
            logger.warning("Ignoring pinned_kitchen entry that is not a kitchen ID: %r", value)
            continue
        if kitchen_id not in ids:
            ids.append(kitchen_id)
    return ids


def _get_user(session: Session, user_id: uuid.UUID, lock: bool = False) -> User:
    statement = select(User).where(User.user_id == user_id)
    user = session.scalars(statement.with_for_update() if lock else statement).first()
    if user is None:
        raise NotFoundError("User", user_id)
    return user


def kitchen_society_all(
    session: Session, user_id: uuid.UUID, society_id: uuid.UUID | None
) -> list[HomeKitchenOut]:
    """The user's pinned kitchens (in pinned order) followed by the society's other kitchens
    (by name). society_id None means the user's own society."""
    with audit_step("homeKitchenSocietyAll", user_id=user_id, society_id=society_id) as step:
        user = _get_user(session, user_id)
        society_id = society_id or user.society_id
        pinned = pinned_ids(user.pinned_kitchen)
        logger.info("User %s: %d pinned kitchens, society %s", user_id, len(pinned), society_id)

        conditions = []
        if pinned:
            conditions.append(Kitchen.kitchen_id.in_([uuid.UUID(k) for k in pinned]))
        if society_id is not None:
            conditions.append(Kitchen.society_id == society_id)
        if not conditions:
            step.done("no pinned kitchens and no society: 0 kitchens")
            return []

        kitchens = session.scalars(
            select(Kitchen).where(or_(*conditions)).order_by(Kitchen.kitchen_name, Kitchen.kitchen_id)
        ).all()
        rank = {kitchen_id: i for i, kitchen_id in enumerate(pinned)}
        kitchens = sorted(kitchens, key=lambda k: rank.get(str(k.kitchen_id), len(rank)))  # stable
        result = [HomeKitchenOut(**_kitchen_fields(k), pinned=str(k.kitchen_id) in rank)
                  for k in kitchens]
        pinned_found = sum(k.pinned for k in result)
        step.done(f"{len(result)} kitchens ({pinned_found} pinned, "
                  f"{len(result) - pinned_found} from society {society_id})")
        return result


def update_pinned(
    session: Session, user_id: uuid.UUID, kitchen_id: uuid.UUID, pin: bool
) -> PinnedOut:
    """pin=True adds the kitchen to the end of the list (no duplicate); pin=False removes it."""
    with audit_step("homePinnedUpdate", user_id=user_id, kitchen_id=kitchen_id, pin=pin) as step:
        user = _get_user(session, user_id, lock=True)  # row lock: two pin calls cannot lose an update
        before = pinned_ids(user.pinned_kitchen)
        pinned = list(before)
        target = str(kitchen_id)
        if pin:
            if session.get(Kitchen, kitchen_id) is None:
                raise NotFoundError("Kitchen", kitchen_id)
            if target not in pinned:
                pinned.append(target)
        else:
            pinned = [k for k in pinned if k != target]
        user.pinned_kitchen = pinned  # a new list object, so SQLAlchemy sees the change
        session.commit()
        change = "unchanged" if pinned == before else ("pinned" if pin else "unpinned")
        logger.info("User %s kitchen %s %s; %d pinned now", user_id, kitchen_id, change, len(pinned))
        step.done(f"{change}; pinned {before} -> {pinned}")
        return PinnedOut(user_id=user_id, pinned_kitchen=pinned)


def kitchen_live(session: Session, society_id: uuid.UUID) -> list[ActiveKitchenOut]:
    """Kitchens in the society with a dish whose active_order_flag is 1 or 2."""
    with audit_step("homeKitchenLive", society_id=society_id) as step:
        kitchens = _kitchens_with_active_dishes(session, society_id, LIVE_FLAGS)
        step.done(_summary(kitchens))
        return kitchens


def kitchen_preorder(session: Session, society_id: uuid.UUID) -> list[ActiveKitchenOut]:
    """Kitchens in the society with a dish whose active_order_flag is 2."""
    with audit_step("homeKitchenPreorder", society_id=society_id) as step:
        kitchens = _kitchens_with_active_dishes(session, society_id, PREORDER_FLAGS)
        step.done(_summary(kitchens))
        return kitchens


def _kitchens_with_active_dishes(
    session: Session, society_id: uuid.UUID, flags: Collection[int]
) -> list[ActiveKitchenOut]:
    """Kitchens in the society with at least one dish whose active_order_flag is in flags,
    each with those dishes."""
    rows = session.execute(
        select(Kitchen, Dish)
        .join(Dish, Dish.kitchen_id == Kitchen.kitchen_id)
        .where(Kitchen.society_id == society_id, Dish.active_order_flag.in_(list(flags)))
        .order_by(Kitchen.kitchen_name, Kitchen.kitchen_id, Dish.dish_name, Dish.dish_id)
    ).all()
    # every dish's images signed in one Storage call
    signed = storage.signed_images("dish", [dish.images for _, dish in rows],
                                   get_settings().storage_signed_url_seconds)
    kitchens: dict[uuid.UUID, ActiveKitchenOut] = {}
    for (kitchen, dish), images in zip(rows, signed):
        entry = kitchens.get(kitchen.kitchen_id)
        if entry is None:
            entry = kitchens[kitchen.kitchen_id] = ActiveKitchenOut(**_kitchen_fields(kitchen), dishes=[])
        fields = {name: getattr(dish, name) for name in ActiveDishOut.model_fields if name != "images"}
        entry.dishes.append(ActiveDishOut(**fields, images=images))
    return list(kitchens.values())


def _summary(kitchens: list[ActiveKitchenOut]) -> str:
    return f"{len(kitchens)} kitchens, {sum(len(k.dishes) for k in kitchens)} dishes"


def _kitchen_fields(kitchen: Kitchen) -> dict:
    return {column.key: getattr(kitchen, column.key) for column in Kitchen.__table__.columns}
