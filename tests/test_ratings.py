import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.errors import NotFoundError
from app.services.ratings import record_rating_change
from packages.database import AverageRating


def test_new_dish_starts_with_no_reviews(db, data):
    row = db.get(AverageRating, data.dish_off.dish_id)  # created by the all_dishes trigger
    assert row.total_reviews_count == 0 and row.total_stars == 0 and row.average_rating is None
    assert row.kitchen_id == data.kitchen_a1.kitchen_id


def test_add_change_and_remove_ratings(db, data):
    dish_id = data.dish_off.dish_id

    r = record_rating_change(db, dish_id, None, Decimal("4.5"))
    assert (r.total_reviews_count, r.total_stars, r.average_rating) == (1, Decimal("4.5"), Decimal("4.50"))

    r = record_rating_change(db, dish_id, None, 3.0)  # floats are accepted too
    assert (r.total_reviews_count, r.total_stars, r.average_rating) == (2, Decimal("7.5"), Decimal("3.75"))

    r = record_rating_change(db, dish_id, Decimal("4.5"), Decimal("5"))  # rating edited
    assert (r.total_reviews_count, r.total_stars, r.average_rating) == (2, Decimal("8.0"), Decimal("4.00"))

    r = record_rating_change(db, dish_id, Decimal("3"), None)  # review deleted
    assert (r.total_reviews_count, r.total_stars, r.average_rating) == (1, Decimal("5.0"), Decimal("5.00"))

    r = record_rating_change(db, dish_id, Decimal("5"), None)
    assert (r.total_reviews_count, r.total_stars, r.average_rating) == (0, Decimal("0.0"), None)


def test_unknown_dish(db, data):
    with pytest.raises(NotFoundError):
        record_rating_change(db, uuid.uuid4(), None, Decimal("4"))


def test_out_of_range_totals_are_rejected(db, data):
    # removing a review the totals never counted would leave -1 reviews
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            record_rating_change(db, data.dish_off.dish_id, Decimal("4"), None)
