from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db
from app.schemas.account import InstalledOut, UpdateInstalledIn, UserOut
from app.schemas.common import UserIdIn
from app.services import account as service

router = APIRouter(prefix="/account", tags=["account"])


@router.post("/user-info", response_model=UserOut)
def user_info(body: UserIdIn, db: Session = Depends(get_db)):
    """Everything stored about the user."""
    return service.user_info(db, body.user_id)


@router.post("/update-installed", response_model=InstalledOut)
def update_installed(body: UpdateInstalledIn, db: Session = Depends(get_db)):
    """Record whether the user has installed the app (metrics only)."""
    return service.update_installed(db, body.user_id, body.installed)
