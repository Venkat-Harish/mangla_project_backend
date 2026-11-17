import uuid

from packages.database import User


def test_kitchen_society_all_pinned_first(client, data):
    r = client.post("/app/home/kitchen-society-all", json={
        "user_id": str(data.customer.user_id), "society_id": str(data.society_a)})
    assert r.status_code == 200
    got = [(k["kitchen_name"], k["pinned"]) for k in r.json()]
    assert got == [("Test B", True), ("Test A1", False), ("Test A2", False)]


def test_kitchen_society_all_uses_requested_society(client, data, db):
    """A society other than the user's own: only its kitchens, never the user's society's."""
    body = {"user_id": str(data.customer.user_id), "society_id": str(data.society_b)}
    r = client.post("/app/home/kitchen-society-all", json=body)
    assert [(k["kitchen_name"], k["pinned"]) for k in r.json()] == [("Test B", True)]

    data.customer.pinned_kitchen = []
    db.flush()
    r = client.post("/app/home/kitchen-society-all", json=body)
    assert [(k["kitchen_name"], k["pinned"]) for k in r.json()] == [("Test B", False)]


def test_kitchen_society_all_defaults_to_users_society(client, data):
    r = client.post("/app/home/kitchen-society-all", json={"user_id": str(data.customer.user_id)})
    assert [k["kitchen_name"] for k in r.json()] == ["Test B", "Test A1", "Test A2"]


def test_kitchen_society_all_no_duplicates(client, data, db):
    data.customer.pinned_kitchen = [str(data.kitchen_a2.kitchen_id), str(data.kitchen_a2.kitchen_id)]
    db.flush()
    r = client.post("/app/home/kitchen-society-all", json={"user_id": str(data.customer.user_id)})
    assert [(k["kitchen_name"], k["pinned"]) for k in r.json()] == [
        ("Test A2", True), ("Test A1", False)]


def test_update_pinned_pin_and_unpin(client, data, db):
    user = str(data.customer.user_id)
    a1, b = str(data.kitchen_a1.kitchen_id), str(data.kitchen_b.kitchen_id)

    r = client.post("/app/home/update-pinned", json={"user_id": user, "kitchen_id": a1})
    assert r.status_code == 200 and r.json()["pinned_kitchen"] == [b, a1]
    r = client.post("/app/home/update-pinned", json={"user_id": user, "kitchen_id": a1, "pin": True})
    assert r.json()["pinned_kitchen"] == [b, a1]  # pinning twice adds nothing
    r = client.post("/app/home/update-pinned", json={"user_id": user, "kitchen_id": b, "pin": False})
    assert r.json()["pinned_kitchen"] == [a1]
    r = client.post("/app/home/update-pinned", json={"user_id": user, "kitchen_id": b, "pin": False})
    assert r.json()["pinned_kitchen"] == [a1]  # unpinning twice is harmless

    db.expire_all()
    assert db.get(User, data.customer.user_id).pinned_kitchen == [a1]


def test_update_pinned_unknown_rows(client, data):
    user = str(data.customer.user_id)
    r = client.post("/app/home/update-pinned", json={"user_id": user, "kitchen_id": str(uuid.uuid4())})
    assert r.status_code == 404
    r = client.post("/app/home/update-pinned",
                    json={"user_id": str(uuid.uuid4()), "kitchen_id": str(data.kitchen_a1.kitchen_id)})
    assert r.status_code == 404


def test_kitchen_live(client, data):
    r = client.post("/app/home/kitchen-live", json={"society_id": str(data.society_a)})
    assert r.status_code == 200
    kitchens = r.json()
    assert [k["kitchen_name"] for k in kitchens] == ["Test A1"]
    assert [(d["dish_name"], d["active_order_flag"]) for d in kitchens[0]["dishes"]] == [
        ("A1 Live", 1), ("A1 Preorder", 2)]
    assert kitchens[0]["dishes"][0]["dish_price"] == 120.5


def test_kitchen_preorder(client, data):
    r = client.post("/app/home/kitchen-preorder", json={"society_id": str(data.society_a)})
    kitchens = r.json()
    assert [k["kitchen_name"] for k in kitchens] == ["Test A1"]
    assert [d["dish_name"] for d in kitchens[0]["dishes"]] == ["A1 Preorder"]
    r = client.post("/app/home/kitchen-preorder", json={"society_id": str(data.society_b)})
    assert r.json() == []
