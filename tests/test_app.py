"""Request ID, error bodies, CORS on errors, log safety and route layout."""

import logging
import uuid

import pytest
from fastapi.testclient import TestClient

import app.services.account as account_service
from app.main import app


def test_routes_are_post_under_app_prefix():
    routes = {(tuple(r.methods), r.path) for r in app.routes if r.path.startswith("/app/")}
    assert len(routes) == 15
    assert all(methods == ("POST",) for methods, _ in routes)


def test_every_response_gets_a_new_request_id(client, data):
    body = {"user_id": str(data.customer.user_id)}
    first = client.post("/app/account/user-info", json=body)
    second = client.post("/app/account/user-info", json=body)
    ids = [r.headers["X-Request-ID"] for r in (first, second)]
    assert all(uuid.UUID(i).version == 4 for i in ids)
    assert ids[0] != ids[1]


def test_errors_carry_the_request_id(client):
    missing = client.post("/app/account/user-info", json={"user_id": str(uuid.uuid4())})
    assert missing.status_code == 404
    assert missing.json()["request_id"] == missing.headers["X-Request-ID"]

    invalid = client.post("/app/account/user-info", json={"user_id": "not-a-uuid"})
    assert invalid.status_code == 422
    assert invalid.json()["request_id"] == invalid.headers["X-Request-ID"]

    unknown_route = client.post("/app/nope", json={})
    assert unknown_route.status_code == 404
    assert unknown_route.json()["request_id"] == unknown_route.headers["X-Request-ID"]


def test_non_utf8_body_is_a_422_not_a_500(client):
    r = client.post("/app/account/user-info", content=b"\xff\xfe\x00bad",
                    headers={"content-type": "text/plain"})
    assert r.status_code == 422
    assert r.json()["request_id"] == r.headers["X-Request-ID"]


@pytest.fixture
def broken_user_info(monkeypatch):
    def boom(session, user_id):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(account_service, "user_info", boom)


def test_unhandled_error_is_a_500_with_request_id_and_cors(broken_user_info):
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post("/app/account/user-info", json={"user_id": str(uuid.uuid4())},
                        headers={"Origin": "http://example.com"})
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal server error", "request_id": r.headers["X-Request-ID"]}
    assert r.headers["access-control-allow-origin"] == "*"
    assert "X-Request-ID" in r.headers["access-control-expose-headers"]


def test_path_cannot_forge_log_lines(client, caplog):
    caplog.set_level(logging.INFO)
    client.post("/app/x%0D%0AFORGED%20LINE", json={})
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "app.request_id"]
    assert lines and all("\n" not in m and "\r" not in m for m in lines)
    assert any("/app/x%0D%0AFORGED%20LINE" in m for m in lines)
