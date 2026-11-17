import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel, StorableText

# Half stars: 0.5, 1.0, ... 5.0 (all_reviews.rating's check constraint, as a 422 instead of a 500)
Rating = Annotated[Decimal, Field(ge=Decimal("0.5"), le=Decimal("5"), multiple_of=Decimal("0.5"))]
# A path in reviews_photos_and_videos, e.g. 'users/<user_id>/<name>.jpg'
ImagePath = Annotated[StorableText, Field(min_length=1)]


class UserKitchenOrdersIn(BaseModel):
    user_id: uuid.UUID
    kitchen_id: uuid.UUID


class UserSocietyOrdersIn(BaseModel):
    user_id: uuid.UUID
    society_id: uuid.UUID | None = None  # None = the user's own society


class OrderIdIn(BaseModel):
    order_id: uuid.UUID


class OrderReviewIn(BaseModel):
    """/orders/review: the order's user reviews the order's dish."""

    order_id: uuid.UUID
    rating: Rating
    description: StorableText | None = None  # saved as the review's review_text
    # each must be uploaded already, in the order user's folder users/<user_id>/ (/media/upload-url)
    images: list[ImagePath] = Field(default=[], max_length=10)
    anonymous_flag: bool = False


class OrderOut(ORMModel):
    """Every column of the orders table."""

    order_id: uuid.UUID
    order_alphanumeric_id: str
    kitchen_id: uuid.UUID
    dish_id: uuid.UUID
    user_id: uuid.UUID
    portion_count: int
    order_time: datetime
    order_status: str
    payment_id: str | None
    refund_flag: bool
    review_id: uuid.UUID | None  # set once the order has been reviewed (/orders/review)


class OrderListItem(OrderOut):
    kitchen_name: str
    dish_name: str
