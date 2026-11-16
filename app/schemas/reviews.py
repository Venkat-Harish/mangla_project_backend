import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from app.schemas.common import ORMModel


class KitchenIdIn(BaseModel):
    kitchen_id: uuid.UUID


class DishIdIn(BaseModel):
    dish_id: uuid.UUID


class ReviewEditIn(BaseModel):
    review_id: uuid.UUID
    review_text: str | None = None  # None = keep the current text
    add_images: list[str] = []
    remove_images: list[str] = []

    @model_validator(mode="after")
    def something_to_change(self):
        if self.review_text is None and not self.add_images and not self.remove_images:
            raise ValueError("give review_text, add_images or remove_images")
        return self


class LikeCounterIn(BaseModel):
    review_id: uuid.UUID
    like_flag: Literal[0, 1]  # 1 = like, 0 = dislike


class ReviewOut(ORMModel):
    review_id: uuid.UUID
    review_alphanumeric_id: str
    dish_id: uuid.UUID
    dish_name: str
    kitchen_id: uuid.UUID
    # user_id, user_name and order_id are null for an anonymous review everywhere except the
    # reviewer's own list (/review/user-all); order_id would lead to the reviewer via /orders/details
    order_id: uuid.UUID | None
    user_id: uuid.UUID | None
    user_name: str | None
    rating: float
    review_text: str | None
    images: list[Any]
    anonymous_flag: bool
    review_time: datetime
    last_edited_time: datetime | None
    like_count: int
    dislike_count: int


class LikeCountsOut(BaseModel):
    review_id: uuid.UUID
    like_count: int
    dislike_count: int
