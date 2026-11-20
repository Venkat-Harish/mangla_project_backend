"""average_ratings upkeep: every change to a review's rating goes through record_rating_change.

The database keeps one average_ratings row per dish and computes average_rating from the two
totals; the backend keeps the totals right. Call record_rating_change in the same transaction
as the review write, before commit:

    new review         record_rating_change(session, dish_id, None, rating)
    rating changed     record_rating_change(session, dish_id, old_rating, new_rating)
    review deleted     record_rating_change(session, dish_id, old_rating, None)
"""

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from packages.database import AverageRating

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DishRating:
    dish_id: uuid.UUID
    total_reviews_count: int
    total_stars: Decimal
    average_rating: Decimal | None  # None when the dish has no reviews


def _stars(rating: Decimal | float | None) -> Decimal:
    return Decimal("0") if rating is None else Decimal(str(rating))


def record_rating_change(
    session: Session,
    dish_id: uuid.UUID,
    old_rating: Decimal | float | None,
    new_rating: Decimal | float | None,
) -> DishRating:
    """Apply one review's rating change to its dish's totals in a single atomic UPDATE, so
    concurrent requests can't lose each other's changes. Does not commit.

    old_rating None = the review is new; new_rating None = the review is deleted.
    Raises NotFoundError if the dish has no average_ratings row (i.e. the dish doesn't exist).
    A total that would go out of range (e.g. more stars than 5 x reviews) is rejected by the
    database's check constraint.
    """
    count_delta = (new_rating is not None) - (old_rating is not None)
    stars_delta = _stars(new_rating) - _stars(old_rating)
    row = session.execute(
        update(AverageRating)
        .where(AverageRating.dish_id == dish_id)
        .values(total_reviews_count=AverageRating.total_reviews_count + count_delta,
                total_stars=AverageRating.total_stars + stars_delta)
        .returning(AverageRating.dish_id, AverageRating.total_reviews_count,
                   AverageRating.total_stars, AverageRating.average_rating)
        .execution_options(synchronize_session=False)
    ).first()
    if row is None:
        raise NotFoundError("Dish", dish_id)
    rating = DishRating(**row._mapping)
    logger.info("Dish %s rating totals %+d reviews, %+s stars -> %d reviews, average %s",
                dish_id, count_delta, stars_delta, rating.total_reviews_count, rating.average_rating)
    return rating
