from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.media import UploadUrlIn, UploadUrlOut
from app.services import media as service

router = APIRouter(prefix="/media", tags=["media"])


@router.post("/upload-url", response_model=UploadUrlOut)
def upload_url(body: UploadUrlIn, db: Session = Depends(get_db)):
    """Signed URLs to upload photos or videos; send the returned paths to the saving endpoint."""
    return service.upload_urls(db, body.kind, body.user_id, body.file_names)
