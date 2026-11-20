import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, Integer, Numeric, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base
from ..ddl import add_average_rating_rows, enable_rls


class AverageRating(Base):
    """One row per dish. The backend updates the two totals whenever reviews change;
    average_rating is computed by the database from them."""

    __tablename__ = "average_ratings"
    __table_args__ = (
        Index("ix_average_ratings_kitchen_id_dish_id", "kitchen_id", "dish_id"),
        CheckConstraint(
            "total_reviews_count >= 0", name="ck_average_ratings_total_reviews_count_nonnegative"
        ),
        # Each review is 0.5-5 stars, so the total must fit between those bounds
        CheckConstraint(
            "total_stars >= 0.5 * total_reviews_count AND total_stars <= 5 * total_reviews_count",
            name="ck_average_ratings_total_stars_in_range",
        ),
    )

    dish_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("all_dishes.dish_id", ondelete="CASCADE"),
        primary_key=True,
    )
    total_reviews_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    total_stars: Mapped[Decimal] = mapped_column(
        Numeric(10, 1), nullable=False, server_default=text("0")
    )
    # Generated column (read-only): total_stars / total_reviews_count, NULL with no reviews
    average_rating: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(3, 2),
        Computed(
            "CASE WHEN total_reviews_count > 0 "
            "THEN round(total_stars / total_reviews_count, 2) END",
            persisted=True,
        ),
    )
    kitchen_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("all_kitchens.kitchen_id"), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AverageRating {self.dish_id} {self.average_rating} ({self.total_reviews_count})>"


add_average_rating_rows(AverageRating.__table__)
enable_rls(AverageRating.__table__)
