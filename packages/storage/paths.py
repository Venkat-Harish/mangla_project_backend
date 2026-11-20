"""File paths inside a bucket: the folder of a kind for some IDs, new file names, and checks.

Paths never start with '/' and never include the bucket name, e.g. 'users/<user_id>/<name>.jpg'.
"""

import uuid

from .storage_config import ALLOWED_EXTENSIONS, MEDIA_KINDS


def folder(kind: str, **ids) -> str:
    """The kind's folder for these IDs, e.g. folder("review", user_id=u) -> 'users/<u>/'."""
    return MEDIA_KINDS[kind].folder.format(**{name: str(value) for name, value in ids.items()})


def extension(file_name: str) -> str | None:
    """The file's lower-case extension if it is an allowed photo or video type, else None."""
    stem, dot, ext = file_name.rpartition(".")
    ext = ext.lower()
    return ext if dot and stem and ext in ALLOWED_EXTENSIONS else None


def new_path(kind: str, file_name: str, **ids) -> str:
    """A new, unique path for an upload: the folder + a random name + the original extension.
    The app's file name is not used, so uploads never overwrite each other."""
    ext = extension(file_name)
    if ext is None:
        raise ValueError(f"not an allowed photo or video type: {file_name!r}")
    return f"{folder(kind, **ids)}{uuid.uuid4().hex}.{ext}"


def is_in_folder(kind: str, path: object, **ids) -> bool:
    """True only for one allowed file directly inside the kind's folder for these IDs:
    no subfolders, no '..', no hidden files such as .emptyFolderPlaceholder."""
    if not isinstance(path, str):
        return False
    prefix = folder(kind, **ids)
    if not path.startswith(prefix):
        return False
    name = path[len(prefix):]
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return False
    return extension(name) is not None
