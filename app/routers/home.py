from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.home import (
    ActiveKitchenOut, HomeKitchenOut, KitchenSocietyAllIn, PinnedOut, SocietyIn, UpdatePinnedIn,
)
from app.services import home as service

router = APIRouter(prefix="/home", tags=["home"])


@router.post("/kitchen-society-all", response_model=list[HomeKitchenOut])
def kitchen_society_all(body: KitchenSocietyAllIn, db: Session = Depends(get_db)):
    """The user's pinned kitchens first, then every other kitchen in the society."""
    return service.kitchen_society_all(db, body.user_id, body.society_id)


@router.post("/update-pinned", response_model=PinnedOut)
def update_pinned(body: UpdatePinnedIn, db: Session = Depends(get_db)):
    """Pin (pin=true) or unpin (pin=false) a kitchen; returns the new pinned list."""
    return service.update_pinned(db, body.user_id, body.kitchen_id, body.pin)


@router.post("/kitchen-live", response_model=list[ActiveKitchenOut])
def kitchen_live(body: SocietyIn, db: Session = Depends(get_db)):
    """Kitchens in the society with a dish whose active_order_flag is 1 or 2."""
    return service.kitchen_live(db, body.society_id)


@router.post("/kitchen-preorder", response_model=list[ActiveKitchenOut])
def kitchen_preorder(body: SocietyIn, db: Session = Depends(get_db)):
    """Kitchens in the society with a dish whose active_order_flag is 2."""
    return service.kitchen_preorder(db, body.society_id)
