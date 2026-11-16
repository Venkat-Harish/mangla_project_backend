from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.common import UserIdIn
from app.schemas.orders import (
    OrderIdIn, OrderListItem, OrderOut, UserKitchenOrdersIn, UserSocietyOrdersIn,
)
from app.services import orders as service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/user-all", response_model=list[OrderListItem])
def user_all(body: UserIdIn, db: Session = Depends(get_db)):
    """All orders placed by the user, newest first."""
    return service.user_all(db, body.user_id)


@router.post("/user-kitchen", response_model=list[OrderListItem])
def user_kitchen(body: UserKitchenOrdersIn, db: Session = Depends(get_db)):
    """The user's orders from one kitchen, newest first."""
    return service.user_kitchen(db, body.user_id, body.kitchen_id)


@router.post("/user-society", response_model=list[OrderListItem])
def user_society(body: UserSocietyOrdersIn, db: Session = Depends(get_db)):
    """The user's orders from kitchens in one society (default: the user's own), newest first."""
    return service.user_society(db, body.user_id, body.society_id)


@router.post("/details", response_model=OrderOut)
def details(body: OrderIdIn, db: Session = Depends(get_db)):
    """Every column of one order."""
    return service.details(db, body.order_id)
