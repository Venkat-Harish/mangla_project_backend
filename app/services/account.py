"""Account: everything stored about a user. Logged, not audited."""

import uuid

from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.schemas.account import UserOut
from app.steps import log_step
from packages.database import User


def user_info(session: Session, user_id: uuid.UUID) -> UserOut:
    with log_step("accountUserInfo", user_id=user_id) as step:
        user = session.get(User, user_id)
        if user is None:
            raise NotFoundError("User", user_id)
        step.done(f"found user (kitchen_flag={user.kitchen_flag})")
        return UserOut.model_validate(user)
