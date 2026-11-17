"""Reviews: by user, kitchen or dish; edit text/images; like/dislike counters.

Images are paths in the reviews_photos_and_videos bucket, in the reviewer's folder
(users/<user_id>/); outputs add a signed URL to each (packages.storage).

Audited in review_audit: reviewUserAll, reviewKitchen, reviewDish, reviewEdit, reviewLikeCounter.
"""

import logging
import uuid

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import InvalidInputError, NotFoundError
from app.schemas.reviews import LikeCountsOut, ReviewOut
from app.steps import audit_step
from packages import storage
from packages.database import Dish, Review, User

logger = logging.getLogger(__name__)


def _reviews() -> Select:
    """Reviews with dish name, kitchen and reviewer name, newest first."""
    return (
        select(*Review.__table__.columns, Dish.dish_name, Dish.kitchen_id, User.user_name)
        .join(Dish, Dish.dish_id == Review.dish_id)
        .join(User, User.user_id == Review.user_id)
        .order_by(Review.review_time.desc(), Review.review_id)
    )


def _run(session: Session, statement: Select, hide_anonymous: bool) -> list[ReviewOut]:
    """hide_anonymous: blank out everything that identifies who wrote an anonymous review: the
    user, and the order (which /orders/details would map back to the user)."""
    rows = session.execute(statement).mappings().all()
    # every review's images signed in one Storage call
    signed = storage.signed_images("review", [row["images"] for row in rows],
                                   get_settings().storage_signed_url_seconds)
    reviews = []
    for row, images in zip(rows, signed):
        review = ReviewOut.model_validate({**row, "images": images})
        if hide_anonymous and review.anonymous_flag:
            review = review.model_copy(update={"user_id": None, "user_name": None, "order_id": None})
        reviews.append(review)
    return reviews


def _summary(reviews: list[ReviewOut]) -> str:
    if not reviews:
        return "0 reviews"
    average = sum(r.rating for r in reviews) / len(reviews)
    return f"{len(reviews)} reviews, average rating {average:.2f}"


def user_all(session: Session, user_id: uuid.UUID) -> list[ReviewOut]:
    """The user's own reviews; anonymous ones still show the user, since they are the reader."""
    with audit_step("reviewUserAll", user_id=user_id) as step:
        reviews = _run(session, _reviews().where(Review.user_id == user_id), hide_anonymous=False)
        step.done(_summary(reviews))
        return reviews


def for_kitchen(session: Session, kitchen_id: uuid.UUID) -> list[ReviewOut]:
    with audit_step("reviewKitchen", kitchen_id=kitchen_id) as step:
        reviews = _run(session, _reviews().where(Dish.kitchen_id == kitchen_id), hide_anonymous=True)
        step.done(_summary(reviews))
        return reviews


def for_dish(session: Session, dish_id: uuid.UUID) -> list[ReviewOut]:
    with audit_step("reviewDish", dish_id=dish_id) as step:
        reviews = _run(session, _reviews().where(Review.dish_id == dish_id), hide_anonymous=True)
        step.done(_summary(reviews))
        return reviews


def edit(
    session: Session,
    review_id: uuid.UUID,
    review_text: str | None,
    add_images: list[str],
    remove_images: list[str],
) -> ReviewOut:
    """Change the text and/or images. Images are removed first, then added (no duplicates).
    An added image must be a file already uploaded to the reviewer's folder; a removed one is
    only taken off the review (the file stays in Storage).
    The database trigger sets last_edited_time when the content actually changes."""
    with audit_step("reviewEdit", review_id=review_id, text_changed=review_text is not None,
                    add_images=add_images, remove_images=remove_images) as step:
        reviewer = session.scalar(select(Review.user_id).where(Review.review_id == review_id))
        if reviewer is None:
            raise NotFoundError("Review", review_id)
        if add_images:
            check_uploaded(reviewer, add_images, "add_images")  # before the row lock: it calls Storage
        review = session.scalars(
            select(Review).where(Review.review_id == review_id).with_for_update()
        ).first()
        if review is None:
            raise NotFoundError("Review", review_id)
        changes = []
        if review_text is not None:
            review.review_text = review_text
            changes.append("text updated")
        if add_images or remove_images:
            before = list(review.images or [])
            removed = set(remove_images)
            images = [image for image in before if image not in removed]
            for image in add_images:
                if image not in images:
                    images.append(image)
            review.images = images  # a new list object, so SQLAlchemy sees the change
            changes.append(f"images {len(before)} -> {len(images)}")
            missing = removed - set(before)
            if missing:
                logger.info("Review %s: %d images to remove were not on the review",
                            review_id, len(missing))
        session.commit()
        logger.info("Review %s edited: %s", review_id, ", ".join(changes))
        step.done(", ".join(changes))
        # The request names no requester, so an anonymous review stays anonymous here too;
        # otherwise any client could unmask a reviewer with an edit that changes nothing.
        return review_out(session, review_id, hide_anonymous=True)


def review_out(session: Session, review_id: uuid.UUID, hide_anonymous: bool) -> ReviewOut:
    """One review as the review endpoints return it (dish, kitchen, reviewer, signed images)."""
    return _run(session, _reviews().where(Review.review_id == review_id), hide_anonymous)[0]


def check_uploaded(user_id: uuid.UUID, paths: list[str], field: str) -> None:
    """Every path must be a file directly in the reviewer's folder, and uploaded already.
    field names the request field in the 422 message. Calls Storage: don't hold row locks."""
    folder = storage.folder("review", user_id=user_id)
    outside = [p for p in paths if not storage.is_in_folder("review", p, user_id=user_id)]
    if outside:
        raise InvalidInputError(f"{field} must be photo or video files in {folder}: {outside}")
    uploaded = storage.existing_files("review", user_id=user_id)
    missing = [p for p in dict.fromkeys(paths) if p not in uploaded]
    if missing:
        raise InvalidInputError(f"{field} not uploaded yet: {missing}")


def like_counter(session: Session, review_id: uuid.UUID, like_flag: int) -> LikeCountsOut:
    """like_flag 1 adds one like, 0 adds one dislike, in a single atomic UPDATE."""
    kind = "like" if like_flag == 1 else "dislike"
    with audit_step("reviewLikeCounter", review_id=review_id, like_flag=like_flag) as step:
        column = Review.like_count if like_flag == 1 else Review.dislike_count
        row = session.execute(
            update(Review)
            .where(Review.review_id == review_id)
            .values({column: column + 1})
            .returning(Review.review_id, Review.like_count, Review.dislike_count)
            .execution_options(synchronize_session=False)
        ).first()
        if row is None:
            raise NotFoundError("Review", review_id)
        session.commit()
        counts = LikeCountsOut.model_validate(row._mapping)
        step.done(f"{kind} added: likes={counts.like_count}, dislikes={counts.dislike_count}")
        return counts
