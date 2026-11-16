import uuid
from typing import Any

from pydantic import BaseModel


class CartItemOut(BaseModel):
    """One cart entry, with the dish's current details (null when the dish no longer exists)."""

    dish_id: str
    portion_count: int | None
    available: bool  # false when the dish no longer exists
    dish_name: str | None = None
    dish_price: float | None = None
    images: list[Any] = []
    active_order_flag: int | None = None
    kitchen_id: uuid.UUID | None = None
    kitchen_name: str | None = None


class CartOut(BaseModel):
    user_id: uuid.UUID
    items: list[CartItemOut]
