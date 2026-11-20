"""Supabase Storage settings: credentials from .env, and the bucket and folder of each media kind.

The folders and what they hold are described in buckets.md (the backend root).
"""

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from dotenv import load_dotenv

from .errors import StorageError

# mangla_backend/.env  (packages/storage/storage_config.py -> parents[2] is the backend root)
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass(frozen=True)
class MediaKind:
    bucket: str
    folder: str  # format string filled with the IDs; always ends with '/'


# One entry per kind of media file. A kind's files sit directly inside its folder.
MEDIA_KINDS: dict[str, MediaKind] = {
    "review": MediaKind("reviews_photos_and_videos", "users/{user_id}/"),
    "dish": MediaKind("dish_and_kitchen_photos_videos", "dishes_pics/{kitchen_id}/{dish_id}/"),
}

# Photo and video file types that may be uploaded (lower case, without the dot).
ALLOWED_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "heic", "gif", "mp4", "mov", "webm"})

# Seconds to wait for Storage before giving up on a call.
REQUEST_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class Credentials:
    url: str  # https://<project ref>.supabase.co
    key: str  # the secret (service_role) key: full access, backend only

    def __repr__(self) -> str:  # never print the key
        return f"Credentials(url={self.url!r}, key='***')"


@cache
def credentials() -> Credentials:
    """Read on first use, so code that never touches Storage runs without these keys."""
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise StorageError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in mangla_backend/.env")
    return Credentials(url, key)
