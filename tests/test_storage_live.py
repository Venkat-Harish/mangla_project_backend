"""The real Supabase Storage calls, with nothing written: signing a missing file, an upload URL,
and listing an empty folder. Skipped when SUPABASE_URL / SUPABASE_SECRET_KEY are not set."""

import os
import uuid

import pytest

from packages import storage

pytestmark = [
    pytest.mark.live_storage,
    pytest.mark.skipif(not (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SECRET_KEY")),
                       reason="Storage keys not in .env"),
]


def test_live_storage_calls():
    user_id = uuid.uuid4()  # a folder that has no files
    missing = f"users/{user_id}/missing.jpg"
    assert storage.signed_images("review", [[missing]], 60) == [[{"path": missing, "url": None}]]

    path, url = storage.create_upload("review", "a.jpg", user_id=user_id)
    assert storage.is_in_folder("review", path, user_id=user_id)
    assert url.startswith(os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1/object/upload/sign/")
    assert "token=" in url

    assert storage.existing_files("review", user_id=user_id) == set()  # the URL uploads nothing
