"""Photos and videos in Supabase Storage: signed URLs for reading, signed upload URLs, path checks.

Every bucket is private. The database stores each file's path inside its bucket (e.g.
'users/<user_id>/<name>.jpg'); readers get short-lived signed URLs made from those paths.
Callers name a media kind ("review", "dish"); MEDIA_KINDS in storage_config.py maps it to its
bucket and folder. Folders need no creating: one appears with its first file.

    from packages import storage

    storage.signed_images("review", [review.images for review in reviews], expires_in=3600)
    path, url = storage.create_upload("review", "photo.jpg", user_id=user_id)  # app PUTs to url
    storage.is_in_folder("review", path, user_id=user_id)   # path checks before saving one
    storage.existing_files("review", user_id=user_id)       # what is really uploaded there
"""

import logging

from . import client
from .errors import StorageError
from .paths import extension, folder, is_in_folder, new_path
from .storage_config import ALLOWED_EXTENSIONS, MEDIA_KINDS

__all__ = [
    "StorageError", "MEDIA_KINDS", "ALLOWED_EXTENSIONS",
    "folder", "extension", "new_path", "is_in_folder",
    "signed_images", "create_upload", "existing_files",
]

logger = logging.getLogger(__name__)


def signed_images(kind: str, path_lists: list, expires_in: int) -> list[list[dict]]:
    """For each list of stored paths, the same paths as {"path", "url"} dicts, in order.
    All paths are signed in one Storage call. url is None for a file that can't be signed;
    entries that are not strings are dropped with a warning."""
    lists = [value if isinstance(value, list) else [] for value in path_lists]
    paths = [p for paths_ in lists for p in paths_ if isinstance(p, str)]
    dropped = sum(len(paths_) for paths_ in lists) - len(paths)
    if dropped:
        logger.warning("Ignoring %d %s image entries that are not paths", dropped, kind)
    urls = client.sign(MEDIA_KINDS[kind].bucket, paths, expires_in) if paths else {}
    return [[{"path": p, "url": urls.get(p)} for p in paths_ if isinstance(p, str)]
            for paths_ in lists]


def create_upload(kind: str, file_name: str, **ids) -> tuple[str, str]:
    """A new path in the kind's folder for these IDs, and a signed URL to PUT the file to.
    Raises ValueError for a file type that isn't allowed, StorageError if Storage fails."""
    path = new_path(kind, file_name, **ids)
    return path, client.upload_url(MEDIA_KINDS[kind].bucket, path)


def existing_files(kind: str, **ids) -> set[str]:
    """Paths of the files already uploaded to the kind's folder for these IDs."""
    return client.existing(MEDIA_KINDS[kind].bucket, folder(kind, **ids))
