import uuid


def _ids(response):
    return [o["order_id"] for o in response.json()]


def test_user_all_newest_first(client, data):
    r = client.post("/app/orders/user-all", json={"user_id": str(data.customer.user_id)})
    assert r.status_code == 200
    assert _ids(r) == [str(o.order_id) for o in (data.order_new, data.order_b, data.order_old)]
    first = r.json()[0]
    assert first["kitchen_name"] == "Test A1"
    assert first["dish_name"] == "A1 Preorder"
    assert first["order_alphanumeric_id"].startswith("ORD-")


def test_user_all_unknown_user_is_empty(client):
    r = client.post("/app/orders/user-all", json={"user_id": str(uuid.uuid4())})
    assert r.status_code == 200 and r.json() == []


def test_user_kitchen(client, data):
    r = client.post("/app/orders/user-kitchen", json={
        "user_id": str(data.customer.user_id), "kitchen_id": str(data.kitchen_a1.kitchen_id)})
    assert _ids(r) == [str(data.order_new.order_id), str(data.order_old.order_id)]


def test_user_society_given_and_default(client, data):
    user = str(data.customer.user_id)
    given = client.post("/app/orders/user-society",
                        json={"user_id": user, "society_id": str(data.society_b)})
    assert _ids(given) == [str(data.order_b.order_id)]
    default = client.post("/app/orders/user-society", json={"user_id": user})
    assert _ids(default) == [str(data.order_new.order_id), str(data.order_old.order_id)]


def test_user_society_without_society(client, data):
    r = client.post("/app/orders/user-society", json={"user_id": str(data.owner.user_id)})
    assert r.status_code == 200 and r.json() == []
    r = client.post("/app/orders/user-society", json={"user_id": str(uuid.uuid4())})
    assert r.status_code == 404


def test_details(client, data):
    r = client.post("/app/orders/details", json={"order_id": str(data.order_b.order_id)})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"order_id", "order_alphanumeric_id", "kitchen_id", "dish_id", "user_id",
                         "portion_count", "order_time", "order_status", "payment_id", "refund_flag",
                         "review_id"}
    assert body["kitchen_id"] == str(data.kitchen_b.kitchen_id)
    assert body["review_id"] is None  # order_b has no review yet
    reviewed = client.post("/app/orders/details", json={"order_id": str(data.order_old.order_id)})
    assert reviewed.json()["review_id"] == str(data.review_anon.review_id)
    assert body["portion_count"] == 2
    assert client.post("/app/orders/details",
                       json={"order_id": str(uuid.uuid4())}).status_code == 404
