"""Tests run against the real Supabase database inside one transaction per test that is rolled
back afterwards, so nothing they insert or change is kept (services' commit() only releases a
savepoint). Audit rows are written on their own connection, so auditing is off in tests except in
test_audit.py, which deletes its rows. Run from mangla_backend/:  python -m pytest -q
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.deps import get_db
from app.main import app
from app.steps import audit_writer
from packages.database import Dish, Kitchen, Order, Review, User, engine


@pytest.fixture(autouse=True)
def no_audit(monkeypatch):
    monkeypatch.setattr(audit_writer, "enabled", False)


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@dataclass
class Data:
    society_a: uuid.UUID
    society_b: uuid.UUID
    customer: User
    other_user: User
    owner: User
    kitchen_a1: Kitchen
    kitchen_a2: Kitchen
    kitchen_b: Kitchen
    dish_live: Dish
    dish_pre: Dish
    dish_off: Dish
    dish_a2_off: Dish
    dish_b_live: Dish
    order_old: Order
    order_new: Order
    order_b: Order
    review_anon: Review
    review_named: Review


def _phone() -> str:
    return f"+00{uuid.uuid4().int % 10**10:010d}"


@pytest.fixture
def data(db) -> Data:
    """Two societies; customer lives in A, pins kitchen B and has two cart entries (one dish gone).
    Kitchen A1 has a live, a preorder and an off dish; A2 only an off dish; B a live dish.
    Customer ordered twice from A1 and once from B, and wrote an anonymous review."""
    society_a, society_b = uuid.uuid4(), uuid.uuid4()
    owner = User(phone_number=_phone(), user_name="Test Owner", kitchen_flag=True)
    customer = User(phone_number=_phone(), user_name="Test Customer", society_id=society_a)
    other_user = User(phone_number=_phone(), user_name="Test Other", society_id=society_a)
    db.add_all([owner, customer, other_user])
    db.flush()

    kitchen_a1 = Kitchen(kitchen_name="Test A1", society_id=society_a, user_id1=owner.user_id)
    kitchen_a2 = Kitchen(kitchen_name="Test A2", society_id=society_a, user_id1=owner.user_id)
    kitchen_b = Kitchen(kitchen_name="Test B", society_id=society_b, user_id1=owner.user_id)
    db.add_all([kitchen_a1, kitchen_a2, kitchen_b])
    db.flush()

    def dish(kitchen, name, flag):
        return Dish(kitchen_id=kitchen.kitchen_id, dish_name=name, dish_price=Decimal("120.50"),
                    images=[], active_order_flag=flag)

    dish_live = dish(kitchen_a1, "A1 Live", 1)
    dish_pre = dish(kitchen_a1, "A1 Preorder", 2)
    dish_off = dish(kitchen_a1, "A1 Off", 0)
    dish_a2_off = dish(kitchen_a2, "A2 Off", 0)
    dish_b_live = dish(kitchen_b, "B Live", 1)
    db.add_all([dish_live, dish_pre, dish_off, dish_a2_off, dish_b_live])
    db.flush()

    now = datetime.now(timezone.utc)

    def order(kitchen, dish_, hours_ago):
        return Order(kitchen_id=kitchen.kitchen_id, dish_id=dish_.dish_id, user_id=customer.user_id,
                     portion_count=2, order_status="delivered",
                     order_time=now - timedelta(hours=hours_ago))

    order_old = order(kitchen_a1, dish_live, 48)
    order_new = order(kitchen_a1, dish_pre, 1)
    order_b = order(kitchen_b, dish_b_live, 24)
    db.add_all([order_old, order_new, order_b])
    db.flush()

    review_anon = Review(dish_id=dish_live.dish_id, order_id=order_old.order_id,
                         user_id=customer.user_id, rating=Decimal("4.5"), review_text="Tasty",
                         images=["https://img/1.jpg"], anonymous_flag=True,
                         review_time=now - timedelta(hours=2))
    review_named = Review(dish_id=dish_pre.dish_id, order_id=order_new.order_id,
                          user_id=other_user.user_id, rating=Decimal("3.0"), review_text="Okay",
                          images=[], review_time=now - timedelta(hours=1))
    db.add_all([review_anon, review_named])

    customer.pinned_kitchen = [str(kitchen_b.kitchen_id)]
    customer.cart = [
        {"dish_id": str(dish_live.dish_id), "portion_count": 2},
        {"dish_id": str(uuid.uuid4()), "portion_count": 1},
    ]
    db.flush()
    for obj in (order_old, order_new, order_b, review_anon, review_named,
                kitchen_a1, kitchen_a2, kitchen_b):
        db.refresh(obj)  # trigger-generated alphanumeric IDs

    return Data(society_a, society_b, customer, other_user, owner, kitchen_a1, kitchen_a2,
                kitchen_b, dish_live, dish_pre, dish_off, dish_a2_off, dish_b_live,
                order_old, order_new, order_b, review_anon, review_named)
