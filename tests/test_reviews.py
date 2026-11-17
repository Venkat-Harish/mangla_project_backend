import uuid


def test_user_all_shows_own_anonymous_review(client, data):
    r = client.post("/app/review/user-all", json={"user_id": str(data.customer.user_id)})
    assert r.status_code == 200
    reviews = r.json()
    assert [x["review_id"] for x in reviews] == [str(data.review_anon.review_id)]
    review = reviews[0]
    assert review["user_name"] == "Test Customer"
    assert review["rating"] == 4.5
    assert review["dish_name"] == "A1 Live"
    assert review["review_alphanumeric_id"].startswith("REV-")


def test_kitchen_reviews_hide_anonymous_reviewer(client, data):
    r = client.post("/app/review/kitchen", json={"kitchen_id": str(data.kitchen_a1.kitchen_id)})
    reviews = r.json()
    assert [x["review_id"] for x in reviews] == [
        str(data.review_named.review_id), str(data.review_anon.review_id)]  # newest first
    named, anon = reviews
    assert named["user_name"] == "Test Other" and named["user_id"] == str(data.other_user.user_id)
    assert named["order_id"] == str(data.order_new.order_id)
    # nothing that leads back to the reviewer: no user, and no order (orders/details has user_id)
    assert anon["user_name"] is None and anon["user_id"] is None and anon["order_id"] is None
    for field in ("dish_id", "review_id", "rating", "review_text", "review_time", "images",
                  "like_count", "dislike_count", "last_edited_time", "kitchen_id"):
        assert field in anon


def test_kitchen_reviews_only_that_kitchen(client, data):
    r = client.post("/app/review/kitchen", json={"kitchen_id": str(data.kitchen_b.kitchen_id)})
    assert r.status_code == 200 and r.json() == []


def test_dish_reviews(client, data):
    r = client.post("/app/review/dish", json={"dish_id": str(data.dish_pre.dish_id)})
    assert [x["review_id"] for x in r.json()] == [str(data.review_named.review_id)]
    r = client.post("/app/review/dish", json={"dish_id": str(data.dish_live.dish_id)})
    [anon] = r.json()
    assert anon["user_id"] is None and anon["order_id"] is None
    r = client.post("/app/review/dish", json={"dish_id": str(data.dish_off.dish_id)})
    assert r.json() == []


def test_edit_does_not_unmask_anonymous_reviewer(client, data):
    """An edit that changes nothing must not reveal who wrote an anonymous review."""
    r = client.post("/app/review/edit", json={"review_id": str(data.review_anon.review_id),
                                              "remove_images": ["https://img/not-there.jpg"]})
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] is None and body["user_name"] is None and body["order_id"] is None
    assert body["images"] == ["https://img/1.jpg"]

    r = client.post("/app/review/edit", json={"review_id": str(data.review_named.review_id),
                                              "review_text": "Okay"})
    assert r.json()["user_name"] == "Test Other"  # a named review still shows its author


def test_edit_text_and_images(client, data):
    review_id = str(data.review_anon.review_id)
    r = client.post("/app/review/edit", json={
        "review_id": review_id,
        "review_text": "Even better the second time",
        "add_images": ["https://img/2.jpg", "https://img/3.jpg", "https://img/2.jpg"],
        "remove_images": ["https://img/1.jpg"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["review_text"] == "Even better the second time"
    assert body["images"] == ["https://img/2.jpg", "https://img/3.jpg"]
    assert body["last_edited_time"] is not None

    r = client.post("/app/review/edit", json={"review_id": review_id,
                                              "remove_images": ["https://img/3.jpg"]})
    assert r.json()["images"] == ["https://img/2.jpg"]
    assert r.json()["review_text"] == "Even better the second time"  # untouched


def test_edit_rejects_empty_and_unknown(client, data):
    r = client.post("/app/review/edit", json={"review_id": str(data.review_anon.review_id)})
    assert r.status_code == 422
    r = client.post("/app/review/edit", json={"review_id": str(uuid.uuid4()), "review_text": "x"})
    assert r.status_code == 404


def test_like_counter(client, data):
    review_id = str(data.review_named.review_id)
    for flag in (1, 1, 0):
        r = client.post("/app/review/like-counter", json={"review_id": review_id, "like_flag": flag})
        assert r.status_code == 200
    assert r.json() == {"review_id": review_id, "like_count": 2, "dislike_count": 1}

    review = client.post("/app/review/dish", json={"dish_id": str(data.dish_pre.dish_id)}).json()[0]
    assert review["last_edited_time"] is None  # likes are not edits


def test_like_counter_rejects_bad_input(client, data):
    review_id = str(data.review_named.review_id)
    r = client.post("/app/review/like-counter", json={"review_id": review_id, "like_flag": 5})
    assert r.status_code == 422
    r = client.post("/app/review/like-counter", json={"review_id": str(uuid.uuid4()), "like_flag": 1})
    assert r.status_code == 404
