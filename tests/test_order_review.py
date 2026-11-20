"""/orders/review: the order's user reviews the order's dish, once per order.

All on data.order_b (customer's 'delivered' order of B Live from kitchen B), the one fixture
order without a review.
"""

import dataclasses
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text, update

from app.config import get_settings
from packages.database import AverageRating, Order, Review
from packages.storage import StorageError
from packages.storage import client as storage_client
from tests.conftest import signed

URL = "/app/orders/review"
BUCKET = "reviews_photos_and_videos"


def _path(user, name: str) -> str:
    return f"users/{user.user_id}/{name}"


def _body(data, **fields) -> dict:
    return {"order_id": str(data.order_b.order_id), "rating": 4, **fields}


def _totals(db, dish_id) -> tuple[int, Decimal]:
    db.expire_all()
    row = db.get(AverageRating, dish_id)
    return row.total_reviews_count, row.total_stars


def _reviews_of(db, order_id) -> list[Review]:
    db.expire_all()
    return db.scalars(select(Review).where(Review.order_id == order_id)).all()


def _nothing_written(db, data, totals_before) -> None:
    assert _reviews_of(db, data.order_b.order_id) == []
    assert db.get(Order, data.order_b.order_id).review_id is None
    assert _totals(db, data.dish_b_live.dish_id) == totals_before


def test_review_an_order(client, data, db, fake_storage):
    p1, p2 = _path(data.customer, "a.jpg"), _path(data.customer, "b.mp4")
    fake_storage.uploaded |= {p1, p2}
    before = _totals(db, data.dish_b_live.dish_id)

    r = client.post(URL, json=_body(data, rating=4.5, description="Lovely", images=[p1, p2, p1]))
    assert r.status_code == 201
    body = r.json()
    review_id = body["review_id"]
    assert body["review_alphanumeric_id"].startswith("REV-")
    assert body["order_id"] == str(data.order_b.order_id)
    assert body["user_id"] == str(data.customer.user_id) and body["user_name"] == "Test Customer"
    assert body["dish_id"] == str(data.dish_b_live.dish_id) and body["dish_name"] == "B Live"
    assert body["kitchen_id"] == str(data.kitchen_b.kitchen_id)
    assert body["rating"] == 4.5 and body["review_text"] == "Lovely"
    assert body["anonymous_flag"] is False and body["like_count"] == 0
    assert body["last_edited_time"] is None
    assert body["images"] == [signed(BUCKET, p1), signed(BUCKET, p2)]  # duplicate dropped

    # the order now points at its review, in details and in the order lists
    details = client.post("/app/orders/details", json={"order_id": str(data.order_b.order_id)})
    assert details.json()["review_id"] == review_id
    orders = client.post("/app/orders/user-all", json={"user_id": str(data.customer.user_id)})
    assert {o["order_id"]: o["review_id"] for o in orders.json()} == {
        str(data.order_new.order_id): str(data.review_named.review_id),
        str(data.order_b.order_id): review_id,
        str(data.order_old.order_id): str(data.review_anon.review_id),
    }
    # the dish's totals count it, and it is listed with the dish's reviews
    assert _totals(db, data.dish_b_live.dish_id) == (before[0] + 1, before[1] + Decimal("4.5"))
    dish = client.post("/app/review/dish", json={"dish_id": str(data.dish_b_live.dish_id)})
    assert [x["review_id"] for x in dish.json()] == [review_id]


def test_allowed_status_in_any_case_and_optional_fields(client, data, db):
    data.order_b.order_status = sorted(get_settings().review_allowed_order_statuses)[0].upper()
    db.flush()
    r = client.post(URL, json={"order_id": str(data.order_b.order_id), "rating": "5"})
    assert r.status_code == 201
    assert r.json()["review_text"] is None and r.json()["images"] == [] and r.json()["rating"] == 5


def test_status_not_allowed(client, data, db):
    assert "cancelled" not in get_settings().review_allowed_order_statuses
    data.order_b.order_status = "cancelled"
    db.flush()
    before = _totals(db, data.dish_b_live.dish_id)
    r = client.post(URL, json=_body(data))
    assert r.status_code == 422
    assert "'cancelled'" in r.json()["detail"]
    assert r.json()["request_id"] == r.headers["X-Request-ID"]
    _nothing_written(db, data, before)


@pytest.mark.parametrize("rating", [4.3, 0, 0.25, 5.5, -1, True, "NaN", None, "four"])
def test_bad_rating(client, data, db, rating):
    before = _totals(db, data.dish_b_live.dish_id)
    r = client.post(URL, json=_body(data, rating=rating))
    assert r.status_code == 422, rating
    _nothing_written(db, data, before)


def test_images_must_be_uploaded_to_the_order_users_folder(client, data, db, fake_storage):
    others = _path(data.other_user, "x.jpg")
    fake_storage.uploaded.add(others)
    before = _totals(db, data.dish_b_live.dish_id)

    r = client.post(URL, json=_body(data, images=[others]))
    assert r.status_code == 422 and r.json()["detail"].startswith("images must be photo or video")

    r = client.post(URL, json=_body(data, images=[_path(data.customer, "never.jpg")]))
    assert r.status_code == 422 and "images not uploaded" in r.json()["detail"]

    assert client.post(URL, json=_body(data, images=[""])).status_code == 422
    eleven = [_path(data.customer, f"{i}.jpg") for i in range(11)]
    fake_storage.uploaded |= set(eleven)
    assert client.post(URL, json=_body(data, images=eleven)).status_code == 422
    _nothing_written(db, data, before)


def test_storage_down_is_502(client, data, db, monkeypatch):
    def down(bucket, folder):
        raise StorageError("Storage unreachable")

    monkeypatch.setattr(storage_client, "existing", down)
    before = _totals(db, data.dish_b_live.dish_id)
    r = client.post(URL, json=_body(data, images=[_path(data.customer, "a.jpg")]))
    assert r.status_code == 502 and r.json()["request_id"] == r.headers["X-Request-ID"]
    _nothing_written(db, data, before)


def test_unknown_order(client):
    r = client.post(URL, json={"order_id": str(uuid.uuid4()), "rating": 4})
    assert r.status_code == 404 and r.json()["request_id"] == r.headers["X-Request-ID"]


def test_second_review_is_a_conflict(client, data, db):
    assert client.post(URL, json=_body(data, rating=4)).status_code == 201
    before = _totals(db, data.dish_b_live.dish_id)

    r = client.post(URL, json=_body(data, rating=1))
    assert r.status_code == 409 and "already reviewed" in r.json()["detail"]
    assert r.json()["request_id"] == r.headers["X-Request-ID"]
    assert len(_reviews_of(db, data.order_b.order_id)) == 1
    assert _totals(db, data.dish_b_live.dish_id) == before

    # the fixture's orders were reviewed already too
    r = client.post(URL, json={"order_id": str(data.order_old.order_id), "rating": 2})
    assert r.status_code == 409


def test_review_saved_meanwhile_is_a_conflict(client, data, db, fake_storage, monkeypatch):
    """Another request reviews the order after the first check, while this one is in Storage:
    the re-check under the row lock must see it (not the session's stale copy of the order)."""
    path = _path(data.customer, "a.jpg")
    fake_storage.uploaded.add(path)
    faked_existing = storage_client.existing

    def existing_while_another_review_lands(bucket, folder):
        other = Review(dish_id=data.dish_b_live.dish_id, order_id=data.order_b.order_id,
                       user_id=data.customer.user_id, rating=Decimal("2"), images=[])
        db.add(other)
        db.flush()
        db.execute(update(Order).where(Order.order_id == data.order_b.order_id)
                   .values(review_id=other.review_id)
                   .execution_options(synchronize_session=False))
        return faked_existing(bucket, folder)

    monkeypatch.setattr(storage_client, "existing", existing_while_another_review_lands)
    before = _totals(db, data.dish_b_live.dish_id)
    r = client.post(URL, json=_body(data, rating=5, images=[path]))
    assert r.status_code == 409
    assert [x.rating for x in _reviews_of(db, data.order_b.order_id)] == [Decimal("2")]
    assert _totals(db, data.dish_b_live.dish_id) == before


def test_anonymous_review_hides_the_reviewer(client, data):
    r = client.post(URL, json=_body(data, rating=3, anonymous_flag=True))
    assert r.status_code == 201
    body = r.json()
    assert body["anonymous_flag"] is True
    assert body["user_id"] is None and body["user_name"] is None and body["order_id"] is None

    own = client.post("/app/review/user-all", json={"user_id": str(data.customer.user_id)})
    mine = [x for x in own.json() if x["review_id"] == body["review_id"]]
    assert mine and mine[0]["user_name"] == "Test Customer"  # the reviewer's own list shows it


def test_schema_has_the_review_id_constraints_and_posts_audit(db):
    names = set(db.scalars(text(
        "SELECT conname FROM pg_constraint WHERE conname IN "
        "('orders_review_id_key', 'orders_review_id_fkey', 'all_reviews_order_id_key')")))
    assert names == {"orders_review_id_key", "orders_review_id_fkey", "all_reviews_order_id_key"}
    assert db.scalar(text("SELECT to_regclass('public.posts_audit')")) is not None


def test_allowed_statuses_come_from_the_setting(client, data, db, monkeypatch):
    import app.services.orders as orders_service

    real = get_settings()

    def allow(*statuses):
        settings = dataclasses.replace(real, review_allowed_order_statuses=frozenset(statuses))
        monkeypatch.setattr(orders_service, "get_settings", lambda: settings)

    allow()  # an empty list refuses every order
    r = client.post(URL, json=_body(data))
    assert r.status_code == 422 and r.json()["detail"].endswith("allowed: none")

    allow("ready")  # data.order_b is 'delivered'
    r = client.post(URL, json=_body(data))
    assert r.status_code == 422 and r.json()["detail"].endswith("allowed: ready")

    data.order_b.order_status = " READY "
    db.flush()
    assert client.post(URL, json=_body(data)).status_code == 201


def test_text_postgres_cannot_store_is_a_422(client, data, db):
    before = _totals(db, data.dish_b_live.dish_id)
    r = client.post(URL, json=_body(data, description="nice\u0000"))
    assert r.status_code == 422 and r.json()["request_id"] == r.headers["X-Request-ID"]
    # r'': the body carries the JSON escape \ud800, which the server decodes to a lone surrogate
    raw = r'{"order_id": "%s", "rating": 4, "description": "a\ud800b"}' % data.order_b.order_id
    r = client.post(URL, content=raw.encode(), headers={"content-type": "application/json"})
    assert r.status_code == 422  # a lone surrogate, valid JSON but not storable text
    _nothing_written(db, data, before)

    r = client.post("/app/review/edit", json={"review_id": str(data.review_named.review_id),
                                              "review_text": "bad\u0000"})
    assert r.status_code == 422

    # an image path is checked the same way, and the 422 that echoes it back still renders
    raw = r'{"order_id": "%s", "rating": 4, "images": ["users/x/a\ud800.jpg"]}' % data.order_b.order_id
    r = client.post(URL, content=raw.encode(), headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["request_id"] == r.headers["X-Request-ID"]
    raw = r'{"review_id": "%s", "add_images": ["a\ud800.jpg"]}' % data.review_named.review_id
    r = client.post("/app/review/edit", content=raw.encode(), headers={"content-type": "application/json"})
    assert r.status_code == 422
