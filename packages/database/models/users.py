import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, false, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    phone_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_name: Mapped[str] = mapped_column(Text, nullable=False)
    society_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    block_number: Mapped[Optional[str]] = mapped_column(Text)
    flat_number: Mapped[Optional[str]] = mapped_column(Text)
    kitchen_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    # users <-> all_kitchens point at each other, so this FK is added with ALTER (use_alter)
    kitchen_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("all_kitchens.kitchen_id", use_alter=True, name="users_kitchen_id_fkey"),
    )
    pinned_kitchen: Mapped[Optional[Any]] = mapped_column(JSONB)
    # timestamptz: stored with time zone; .isoformat() gives ISO 8601 with offset
    kitchen_register_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    user_register_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<User {self.user_id} {self.user_name!r} {self.phone_number}>"
