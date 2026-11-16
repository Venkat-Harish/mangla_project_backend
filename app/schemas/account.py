import uuid
from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel


class UserOut(ORMModel):
    """Every column of the users table."""

    user_id: uuid.UUID
    phone_number: str
    user_name: str
    society_id: uuid.UUID | None
    block_number: str | None
    flat_number: str | None
    kitchen_flag: bool
    kitchen_id: uuid.UUID | None
    pinned_kitchen: Any | None
    cart: Any
    kitchen_register_time: datetime | None
    user_register_time: datetime
