import uuid

from pydantic import BaseModel, ConfigDict


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
