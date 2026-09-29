from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.common.exceptions import BusinessException
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.labs import Lab
from app.models.reservations import Reservation
from app.models.users import User
from app.schemas.reservation import ReservationCreateRequest, reservation_response


router = APIRouter(prefix="/reservation", tags=["预约接口"])


def approved_conflict(
    db: Session, lab_id: int, date, start: str, end: str, exclude_id: int | None = None
) -> bool:
    query = db.query(Reservation.id).filter(
        Reservation.lab_id == lab_id,
        Reservation.date == date,
        Reservation.status == "approved",
        Reservation.start < end,
        Reservation.end > start,
    )
    if exclude_id is not None:
        query = query.filter(Reservation.id != exclude_id)
    # MySQL 的普通查询可能沿用事务开始时的快照；锁定读才能看到刚刚通过的预约。
    return query.with_for_update().first() is not None


@router.post("")
def create_reservation(
    data: ReservationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now()
    if (data.date, data.start) <= (now.date(), now.strftime("%H:%M")):
        raise BusinessException(message="预约开始时间需晚于当前时间")

    # 审核也锁同一间实验室，避免提交与审核同时进行时遗漏时段冲突。
    lab = db.query(Lab).filter(Lab.id == data.lab_id).with_for_update().first()
    if not lab:
        raise BusinessException(code=404, message="实验室不存在")
    if lab.status == "maintenance":
        raise BusinessException(message="实验室维护中，暂不可预约")
    if data.people > lab.capacity:
        raise BusinessException(message=f"预约人数不能超过实验室容量 {lab.capacity} 人")
    if approved_conflict(db, data.lab_id, data.date, data.start, data.end):
        raise BusinessException(code=409, message="该时段已有通过的预约，请选择其他时间")

    reservation = Reservation(
        lab_id=data.lab_id,
        applicant_id=current_user.id,
        date=data.date,
        start=data.start,
        end=data.end,
        people=data.people,
        purpose=data.purpose,
        note=data.note,
        status="pending",
    )
    db.add(reservation)
    db.commit()
    db.refresh(reservation)
    return Response.success(message="预约申请已提交", data=reservation_response(reservation))


@router.get("/mine")
def my_reservations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items = (
        db.query(Reservation)
        .options(joinedload(Reservation.lab), joinedload(Reservation.applicant))
        .filter(Reservation.applicant_id == current_user.id)
        .order_by(Reservation.create_time.desc(), Reservation.id.desc())
        .all()
    )
    return Response.success(data=[reservation_response(item) for item in items])


@router.put("/{reservation_id}/cancel")
def cancel_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not existing or existing.applicant_id != current_user.id:
        raise BusinessException(code=404, message="预约不存在")

    db.query(Lab).filter(Lab.id == existing.lab_id).with_for_update().first()
    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == reservation_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if reservation.status not in ("pending", "approved"):
        raise BusinessException(code=409, message="当前状态不能取消预约")
    reservation.status = "cancelled"
    db.commit()
    db.refresh(reservation)
    return Response.success(message="预约已取消", data=reservation_response(reservation))
