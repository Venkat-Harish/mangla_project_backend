from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.common import UserIdIn
from app.schemas.reviews import (
    DishIdIn, KitchenIdIn, LikeCounterIn, LikeCountsOut, ReviewEditIn, ReviewOut,
)
from app.services import reviews as service

router = APIRouter(prefix="/review", tags=["review"])


@router.post("/user-all", response_model=list[ReviewOut])
def user_all(body: UserIdIn, db: Session = Depends(get_db)):
    """Every review the user wrote, newest first."""
    return service.user_all(db, body.user_id)


@router.post("/kitchen", response_model=list[ReviewOut])
def kitchen(body: KitchenIdIn, db: Session = Depends(get_db)):
    """Reviews of every dish of the kitchen, newest first (anonymous reviewers hidden)."""
    return service.for_kitchen(db, body.kitchen_id)


@router.post("/dish", response_model=list[ReviewOut])
def dish(body: DishIdIn, db: Session = Depends(get_db)):
    """Reviews of one dish, newest first (anonymous reviewers hidden)."""
    return service.for_dish(db, body.dish_id)


@router.post("/edit", response_model=ReviewOut)
def edit(body: ReviewEditIn, db: Session = Depends(get_db)):
    """Change the review text and/or add and remove images."""
    return service.edit(db, body.review_id, body.review_text, body.add_images, body.remove_images)


@router.post("/like-counter", response_model=LikeCountsOut)
def like_counter(body: LikeCounterIn, db: Session = Depends(get_db)):
    """like_flag 1 adds a like, 0 adds a dislike; returns the new counts."""
    return service.like_counter(db, body.review_id, body.like_flag)
