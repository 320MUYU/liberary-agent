from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.users import User
from app.schemas.reservation import ReservationCreateRequest, reservation_response
from app.services import reservation_service

router = APIRouter(prefix="/reservation", tags=["预约接口"])


@router.post("")
def create_reservation(
    data: ReservationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交预约申请

    提前 2 小时、实验室维护中、超出容量、时段冲突这几道校验，
    以及提交时对实验室加锁读的处理，见 reservation_service.create_reservation。
    """
    reservation = reservation_service.create_reservation(db, current_user, data)

    return Response.success(
        message="预约申请已提交", data=reservation_response(reservation)
    )


@router.get("/mine")
def my_reservations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我提交过的预约"""
    items = reservation_service.list_my_reservations(db, current_user)

    return Response.success(data=[reservation_response(item) for item in items])


@router.put("/{reservation_id}/cancel")
def cancel_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """取消预约

    "别人的预约按 404 处理""开始前 2 小时内不能取消"这些规则，
    见 reservation_service.cancel_reservation。
    """
    reservation = reservation_service.cancel_reservation(db, current_user, reservation_id)

    return Response.success(message="预约已取消", data=reservation_response(reservation))
