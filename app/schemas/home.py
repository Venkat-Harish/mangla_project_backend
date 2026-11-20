import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ImageOut, KitchenOut, ORMModel


class KitchenSocietyAllIn(BaseModel):
    user_id: uuid.UUID
    society_id: uuid.UUID | None = None  # None = the user's own society


class UpdatePinnedIn(BaseModel):
    user_id: uuid.UUID
    kitchen_id: uuid.UUID
    pin: bool = True  # true adds the kitchen to the list, false removes it


class SocietyIn(BaseModel):
    society_id: uuid.UUID


class HomeKitchenOut(KitchenOut):
    pinned: bool


class PinnedOut(BaseModel):
    user_id: uuid.UUID
    pinned_kitchen: list[str]


class ActiveDishOut(ORMModel):
    dish_id: uuid.UUID
    dish_name: str
    dish_price: float
    images: list[ImageOut]
    description: str | None
    active_order_flag: int
    order_close_time: datetime | None
    pickup_time: datetime | None
    portions_count: int | None


class ActiveKitchenOut(KitchenOut):
    dishes: list[ActiveDishOut]
