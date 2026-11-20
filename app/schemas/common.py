import uuid
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict


def _storable_text(value: str) -> str:
    """Text Postgres can store. A NUL character or a lone UTF-16 surrogate (both valid in JSON)
    would make the INSERT fail with a 500; this turns them into a 422 instead."""
    if "\x00" in value:
        raise ValueError("must not contain NUL (\\u0000) characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("must be valid Unicode text (no lone surrogates)") from None
    return value


# Free text saved to a text column, e.g. a review's description
StorableText = Annotated[str, AfterValidator(_storable_text)]


class ORMModel(BaseModel):
    """Response model that can be built from an ORM object or a row mapping."""

    model_config = ConfigDict(from_attributes=True)


class ImageOut(BaseModel):
    """A photo or video: its path in the bucket (what the database stores and endpoints take
    back), and a short-lived signed URL to show it (null if the file can't be signed)."""

    path: str
    url: str | None


class UserIdIn(BaseModel):
    user_id: uuid.UUID


class KitchenOut(ORMModel):
    kitchen_id: uuid.UUID
    kitchen_alphanumeric_id: str
    kitchen_name: str
    society_id: uuid.UUID | None
    user_id1: uuid.UUID
    user_id2: uuid.UUID | None
    user_id3: uuid.UUID | None
