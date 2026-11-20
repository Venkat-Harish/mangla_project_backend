"""Account: everything stored about a user (logged, not audited), and the app-installed flag
(audited, since it writes)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.schemas.account import InstalledOut, UserOut
from app.steps import audit_step, log_step
from packages.database import User


def user_info(session: Session, user_id: uuid.UUID) -> UserOut:
    with log_step("accountUserInfo", user_id=user_id) as step:
        user = session.get(User, user_id)
        if user is None:
            raise NotFoundError("User", user_id)
        step.done(f"found user (kitchen_flag={user.kitchen_flag})")
        return UserOut.model_validate(user)


def update_installed(session: Session, user_id: uuid.UUID, installed: bool) -> InstalledOut:
    """Record whether the user has installed the app (home-screen PWA). Used for metrics only."""
    with audit_step("accountInstalledUpdate", user_id=user_id, installed=installed) as step:
        user = session.scalars(select(User).where(User.user_id == user_id).with_for_update()).first()
        if user is None:
            raise NotFoundError("User", user_id)
        before = user.app_installed
        user.app_installed = installed
        session.commit()
        step.done("unchanged" if before == installed else f"app_installed {before} -> {installed}")
        return InstalledOut(user_id=user_id, app_installed=installed)
