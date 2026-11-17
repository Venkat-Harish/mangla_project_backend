"""packages.storage path rules (no Storage calls)."""

import uuid

import pytest

from packages import storage


def test_folders():
    u, k, d = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert storage.folder("review", user_id=u) == f"users/{u}/"
    assert storage.folder("dish", kitchen_id=k, dish_id=d) == f"dishes_pics/{k}/{d}/"


def test_extension():
    assert storage.extension("a.JPG") == "jpg"
    assert storage.extension("my.clip.mov") == "mov"
    for name in ("a.txt", "jpg", ".jpg", "a.", "a"):
        assert storage.extension(name) is None, name


def test_new_path():
    u = uuid.uuid4()
    first = storage.new_path("review", "Photo.PNG", user_id=u)
    second = storage.new_path("review", "Photo.PNG", user_id=u)
    assert first.startswith(f"users/{u}/") and first.endswith(".png") and first != second
    assert storage.is_in_folder("review", first, user_id=u)
    with pytest.raises(ValueError):
        storage.new_path("review", "notes.txt", user_id=u)


def test_is_in_folder():
    u = uuid.uuid4()
    mine = f"users/{u}/"
    assert storage.is_in_folder("review", mine + "a.jpg", user_id=u)
    for path in (f"users/{uuid.uuid4()}/a.jpg", mine, mine + "../a.jpg", mine + "x/a.jpg",
                 mine + ".emptyFolderPlaceholder", mine + "a.txt", mine + "a\\b.jpg",
                 "/" + mine + "a.jpg", None, 5):
        assert not storage.is_in_folder("review", path, user_id=u), path
