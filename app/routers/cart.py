from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.cart import CartOut
from app.schemas.common import UserIdIn
from app.services import cart as service

router = APIRouter(prefix="/cart", tags=["cart"])


@router.post("/user", response_model=CartOut)
def user_cart(body: UserIdIn, db: Session = Depends(get_db)):
    """The items in the user's cart, with portion counts and current dish details."""
    return service.user_cart(db, body.user_id)
