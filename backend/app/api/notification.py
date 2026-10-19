from fastapi import APIRouter, Depends, Path, Query

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.schemas.notification import ReadAllNotifications
from app.services import notification_service


router = APIRouter(prefix="/notifications", tags=["读者消息通知"])


@router.get("")
def list_notifications(page: int = Query(default=1, ge=1), page_size: int = Query(default=10, ge=1, le=100),
        unread_only: bool = Query(default=False), user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=notification_service.list_notifications(
        db, user.id, page=page, page_size=page_size, unread_only=unread_only))


@router.post("/read-all")
def mark_all_read(data: ReadAllNotifications, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data={"updated": notification_service.mark_all_read(db, user.id, data.through_id)})


@router.post("/{notification_id}/read")
def mark_read(notification_id: int = Path(gt=0), user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=notification_service.mark_read(db, user.id, notification_id))
