"""Media: signed upload URLs for photos and videos (packages.storage). Logged, not audited.

The app asks for upload URLs, PUTs each file to its URL, then sends the returned paths to the
endpoint that saves them (e.g. /review/edit add_images).
"""

import uuid

from sqlalchemy.orm import Session

from app.errors import InvalidInputError, NotFoundError
from app.schemas.media import UploadOut, UploadUrlOut
from app.steps import log_step
from packages import storage
from packages.database import User


def upload_urls(session: Session, kind: str, user_id: uuid.UUID, file_names: list[str]) -> UploadUrlOut:
    """One new path and signed upload URL per file, in the user's folder for this kind."""
    with log_step("mediaUploadUrl", kind=kind, user_id=user_id, files=len(file_names)) as step:
        if session.get(User, user_id) is None:
            raise NotFoundError("User", user_id)
        unsupported = [name for name in file_names if storage.extension(name) is None]
        if unsupported:
            allowed = ", ".join(sorted(storage.ALLOWED_EXTENSIONS))
            raise InvalidInputError(f"not a photo or video type ({allowed}): {unsupported}")
        uploads = []
        for name in file_names:
            path, url = storage.create_upload(kind, name, user_id=user_id)
            uploads.append(UploadOut(file_name=name, path=path, upload_url=url))
        step.done(f"{len(uploads)} upload URLs in {storage.folder(kind, user_id=user_id)}")
        return UploadUrlOut(uploads=uploads)
