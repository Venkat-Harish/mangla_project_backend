import uuid

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Response model that can be built from an ORM object or a row mapping."""

    model_config = ConfigDict(from_attributes=True)


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
