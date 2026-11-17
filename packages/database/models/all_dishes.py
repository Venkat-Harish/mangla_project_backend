import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..ddl import enable_rls


class Dish(Base):
    __tablename__ = "all_dishes"
    __table_args__ = (
        Index("ix_all_dishes_kitchen_id_dish_id", "kitchen_id", "dish_id"),
        CheckConstraint("dish_price >= 0", name="ck_all_dishes_dish_price_nonnegative"),
        CheckConstraint("portions_count >= 0", name="ck_all_dishes_portions_count_nonnegative"),
        CheckConstraint(
            "active_order_flag IN (0, 1, 2)", name="ck_all_dishes_active_order_flag_range"
        ),
    )

    dish_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    kitchen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("all_kitchens.kitchen_id"), nullable=False
    )
    dish_name: Mapped[str] = mapped_column(Text, nullable=False)
    dish_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # File paths in Storage bucket dish_and_kitchen_photos_videos (packages/storage), e.g.
    # ["dishes_pics/<kitchen_id>/<dish_id>/<name>.jpg", ...]
    images: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    description: Mapped[Optional[str]] = mapped_column(Text)
    # 0 = not taking orders, 1 = live, 2 = preorder
    active_order_flag: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    order_close_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    pickup_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    portions_count: Mapped[Optional[int]] = mapped_column(Integer)

    def __repr__(self) -> str:
        return f"<Dish {self.dish_id} {self.dish_name!r} {self.dish_price}>"


enable_rls(Dish.__table__)
