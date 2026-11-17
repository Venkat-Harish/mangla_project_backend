from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.account import UserOut
from app.schemas.common import UserIdIn
from app.services import account as service

router = APIRouter(prefix="/account", tags=["account"])


@router.post("/user-info", response_model=UserOut)
def user_info(body: UserIdIn, db: Session = Depends(get_db)):
    """Everything stored about the user."""
    return service.user_info(db, body.user_id)
