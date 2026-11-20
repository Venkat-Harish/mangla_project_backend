import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class UploadUrlIn(BaseModel):
    kind: Literal["review"]  # the media kind (packages/storage MEDIA_KINDS); "review" for now
    user_id: uuid.UUID  # review: the reviewer, whose folder the files go to
    file_names: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        min_length=1, max_length=10)  # only the extension is kept


class UploadOut(BaseModel):
    file_name: str  # as sent
    path: str  # where the file will be; send it back to the endpoint that saves it
    upload_url: str  # PUT the file here (valid for 2 hours)


class UploadUrlOut(BaseModel):
    uploads: list[UploadOut]  # same order as file_names
