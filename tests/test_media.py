"""/media/upload-url: new paths in the user's folder with signed upload URLs (Storage faked)."""

import uuid


def test_upload_urls_in_users_folder(client, data):
    names = ["holiday.JPG", "clip.mp4", "holiday.JPG"]
    r = client.post("/app/media/upload-url", json={
        "kind": "review", "user_id": str(data.customer.user_id), "file_names": names})
    assert r.status_code == 200
    uploads = r.json()["uploads"]
    assert [u["file_name"] for u in uploads] == names
    folder = f"users/{data.customer.user_id}/"
    paths = [u["path"] for u in uploads]
    assert all(p.startswith(folder) and "/" not in p[len(folder):] for p in paths)
    assert [p.rsplit(".", 1)[1] for p in paths] == ["jpg", "mp4", "jpg"]
    assert len(set(paths)) == 3  # the same file name twice still gets two paths
    for u in uploads:
        assert u["upload_url"] == f"https://upload/reviews_photos_and_videos/{u['path']}?token=t"


def test_upload_urls_rejects_bad_input(client, data):
    user = str(data.customer.user_id)

    def post(**body):
        return client.post("/app/media/upload-url",
                           json={"kind": "review", "user_id": user, "file_names": ["a.jpg"]} | body)

    assert post(user_id=str(uuid.uuid4())).status_code == 404
    r = post(file_names=["a.jpg", "notes.txt", "noext"])
    assert r.status_code == 422 and "notes.txt" in r.json()["detail"]
    assert post(file_names=[]).status_code == 422
    assert post(file_names=[f"{i}.jpg" for i in range(11)]).status_code == 422
    assert post(kind="post").status_code == 422
