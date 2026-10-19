"""Owned inbox queries and writes; event producers retain transaction ownership."""

from datetime import datetime

from sqlalchemy import func

from app.common.exceptions import BusinessException
from app.models.notification import Notification
from app.schemas.notification import NotificationPageResponse, NotificationResponse


def emit_notification(db, *, user_id, event_key, kind, title, content, resource_type, resource_id):
    """Call while holding the corresponding business row lock; never commit here."""
    existing = db.query(Notification).filter_by(user_id=user_id, event_key=event_key).first()
    if existing is not None:
        return existing
    notice = Notification(user_id=user_id, event_key=event_key, kind=kind, title=title, content=content,
        resource_type=resource_type, resource_id=resource_id)
    db.add(notice)
    db.flush()
    return notice


def list_notifications(db, user_id, *, page=1, page_size=10, unread_only=False):
    # A bounded snapshot also supplies the cutoff for "mark all read".
    maximum = db.query(func.max(Notification.id)).filter(Notification.user_id == user_id).scalar() or 0
    query = db.query(Notification).filter(Notification.user_id == user_id, Notification.id <= maximum)
    unread_count = query.filter(Notification.read_at.is_(None)).count()
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))
    total = query.count()
    rows = query.order_by(Notification.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return NotificationPageResponse(items=[NotificationResponse.model_validate(row) for row in rows],
        total=total, unread_count=unread_count, max_id=maximum)


def mark_read(db, user_id, notification_id):
    row = db.query(Notification).filter_by(user_id=user_id, id=notification_id).first()
    if row is None:
        raise BusinessException("通知不存在", 404)
    try:
        db.query(Notification).filter_by(user_id=user_id, id=notification_id).filter(
            Notification.read_at.is_(None)).update({Notification.read_at: datetime.now()}, synchronize_session=False)
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise
    return NotificationResponse.model_validate(row)


def mark_all_read(db, user_id, through_id):
    try:
        count = db.query(Notification).filter(Notification.user_id == user_id,
            Notification.id <= through_id, Notification.read_at.is_(None)).update(
                {Notification.read_at: datetime.now()}, synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return count
