"""Audit rows reach Supabase with the response's request ID; the rows are deleted afterwards.
Also the background writer's queue limit and flush deadline (no database)."""

import json
import logging
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.steps import AuditWriter, audit_writer
from packages.audit import load_audit_config
from packages.database import engine

AUDIT_TABLES = tuple(load_audit_config().tables)  # every table in audit.json


@pytest.fixture
def audit_on(monkeypatch):
    """Auditing on, in the background; every request ID handed to the writer is collected when
    it is submitted (not from responses), so the rows are deleted even if a request fails."""
    monkeypatch.setattr(audit_writer, "enabled", True)
    monkeypatch.setattr(audit_writer, "background", True)
    request_ids: list[str] = []
    submit = audit_writer.submit

    def collecting_submit(call, request_id, *args, **kwargs):
        request_ids.append(str(request_id))
        return submit(call, request_id, *args, **kwargs)

    monkeypatch.setattr(audit_writer, "submit", collecting_submit)
    yield request_ids
    audit_writer.flush(timeout=60)
    if request_ids:
        with engine.begin() as conn:
            for table in AUDIT_TABLES:
                conn.execute(text(f"DELETE FROM public.{table} "
                                  "WHERE request_id = ANY(CAST(:ids AS uuid[]))"),
                             {"ids": request_ids})


def _rows(table: str, request_id: str) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r) for r in conn.execute(
            text(f"SELECT step_name, timestamp, actual_log, error_log FROM public.{table} "
                 "WHERE request_id = :id ORDER BY step_name"), {"id": request_id}).mappings()]


def test_every_audited_step_is_in_audit_json():
    config = load_audit_config()
    for step in ("ordersUserAll", "ordersUserKitchen", "ordersUserSociety", "ordersDetails",
                 "ordersReview",
                 "homeKitchenSocietyAll", "homePinnedUpdate", "homeKitchenLive", "homeKitchenPreorder",
                 "reviewUserAll", "reviewKitchen", "reviewDish", "reviewEdit", "reviewLikeCounter"):
        assert config.table_for(step) is not None, step
    assert config.table_for("ordersUserAll").name == "orders_audit"
    assert config.table_for("homePinnedUpdate").name == "home_audit"
    assert config.table_for("reviewEdit").name == "review_audit"
    assert config.table_for("ordersReview").name == "orders_audit"
    assert set(config.tables) == {"orders_audit", "review_audit", "home_audit", "posts_audit"}
    assert config.tables["posts_audit"].step_names == ()  # no posts endpoints yet


def test_success_and_failure_rows(client, data, audit_on):
    before = datetime.now(timezone.utc)
    ok = client.post("/app/orders/user-all", json={"user_id": str(data.customer.user_id)})
    missing_id = str(uuid.uuid4())
    failed = client.post("/app/orders/details", json={"order_id": missing_id})
    pinned = client.post("/app/home/update-pinned", json={
        "user_id": str(data.customer.user_id), "kitchen_id": str(data.kitchen_a1.kitchen_id)})
    liked = client.post("/app/review/like-counter",
                        json={"review_id": str(data.review_named.review_id), "like_flag": 1})
    after = datetime.now(timezone.utc)
    ids = [r.headers["X-Request-ID"] for r in (ok, failed, pinned, liked)]
    assert set(ids) <= set(audit_on)
    assert audit_writer.flush(timeout=60)

    [row] = _rows("orders_audit", ids[0])
    assert row["step_name"] == "ordersUserAll"
    assert "-> 3 orders (" in row["actual_log"] and row["error_log"] is None
    assert json.loads(row["actual_log"].split(" -> ")[0]) == {"user_id": str(data.customer.user_id)}
    assert before <= row["timestamp"] <= after  # when the step ran, not when the row was written

    [row] = _rows("orders_audit", ids[1])
    assert row["step_name"] == "ordersDetails"
    assert row["error_log"] == f"NotFoundError: Order {missing_id} not found"
    assert "-> failed (" in row["actual_log"]

    [row] = _rows("home_audit", ids[2])
    assert row["step_name"] == "homePinnedUpdate" and "pinned;" in row["actual_log"]

    [row] = _rows("review_audit", ids[3])
    assert row["step_name"] == "reviewLikeCounter" and "likes=1" in row["actual_log"]


def test_order_review_is_audited(client, data, audit_on):
    r = client.post("/app/orders/review", json={"order_id": str(data.order_b.order_id), "rating": 4})
    assert r.status_code == 201
    assert audit_writer.flush(timeout=60)
    [row] = _rows("orders_audit", r.headers["X-Request-ID"])
    assert row["step_name"] == "ordersReview" and row["error_log"] is None
    assert f"review {r.json()['review_id']} saved" in row["actual_log"]


def test_cart_and_account_are_logged_not_audited(client, data, audit_on, caplog):
    caplog.set_level(logging.INFO)
    r = client.post("/app/cart/user", json={"user_id": str(data.customer.user_id)})
    request_id = r.headers["X-Request-ID"]
    assert audit_on == []  # nothing was handed to the audit writer
    assert all(_rows(table, request_id) == [] for table in AUDIT_TABLES)
    messages = [rec.getMessage() for rec in caplog.records if getattr(rec, "request_id", None) == request_id]
    assert any(m.startswith("cartUser finished") for m in messages)
    assert any(m.startswith("Request finished: POST /app/cart/user -> 200") for m in messages)


def test_writer_queue_is_bounded_and_flush_has_a_deadline():
    writer = AuditWriter(enabled=True, background=True, max_pending=2)
    release = threading.Event()
    done = []
    writer.submit(release.wait)  # the worker blocks on this one
    # Room for 2 waiting writes: 1 or 2 of the next three are dropped, depending on whether the
    # worker has already taken the blocking write off the queue.
    writer.submit(done.append, 1)
    writer.submit(done.append, 2)
    writer.submit(done.append, 3)
    assert writer.dropped >= 1
    assert writer.flush(timeout=0.2) is False  # still blocked
    release.set()
    assert writer.flush(timeout=5) is True
    assert writer.pending() == 0
    assert len(done) == 3 - writer.dropped
