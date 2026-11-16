import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class UserKitchenOrdersIn(BaseModel):
    user_id: uuid.UUID
    kitchen_id: uuid.UUID


class UserSocietyOrdersIn(BaseModel):
    user_id: uuid.UUID
    society_id: uuid.UUID | None = None  # None = the user's own society


class OrderIdIn(BaseModel):
    order_id: uuid.UUID


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


class OrderListItem(OrderOut):
    kitchen_name: str
    dish_name: str
