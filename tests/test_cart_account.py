import uuid

from tests.conftest import signed


def test_cart_items_with_dish_details(client, data, db):
    path = f"dishes_pics/{data.kitchen_a1.kitchen_id}/{data.dish_live.dish_id}/a.jpg"
    data.dish_live.images = [path]
    db.flush()
    r = client.post("/app/cart/user", json={"user_id": str(data.customer.user_id)})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert items[0] == {
        "dish_id": str(data.dish_live.dish_id),
        "portion_count": 2,
        "available": True,
        "dish_name": "A1 Live",
        "dish_price": 120.5,
        "images": [signed("dish_and_kitchen_photos_videos", path)],
        "active_order_flag": 1,
        "kitchen_id": str(data.kitchen_a1.kitchen_id),
        "kitchen_name": "Test A1",
    }
    assert items[1]["available"] is False and items[1]["dish_name"] is None


def test_cart_empty_and_unknown_user(client, data):
    r = client.post("/app/cart/user", json={"user_id": str(data.owner.user_id)})
    assert r.json() == {"user_id": str(data.owner.user_id), "items": []}
    assert client.post("/app/cart/user", json={"user_id": str(uuid.uuid4())}).status_code == 404


def test_user_info(client, data):
    r = client.post("/app/account/user-info", json={"user_id": str(data.customer.user_id)})
    assert r.status_code == 200
    body = r.json()
    assert body["user_name"] == "Test Customer"
    assert body["society_id"] == str(data.society_a)
    assert body["pinned_kitchen"] == [str(data.kitchen_b.kitchen_id)]
    assert len(body["cart"]) == 2
    assert set(body) == {"user_id", "phone_number", "user_name", "society_id", "block_number",
                         "flat_number", "kitchen_flag", "kitchen_id", "pinned_kitchen", "cart",
                         "kitchen_register_time", "user_register_time"}
