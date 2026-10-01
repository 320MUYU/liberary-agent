"""预约业务逻辑：学生端提交 / 查询 / 取消 + 管理端审核

并发处理是本模块的重点：提交、取消、审核三个入口都会先对同一间实验室
加锁读（with_for_update），保证"同一时段的冲突判断"是串行的，
不会出现两个请求同时查到"没冲突"然后双双通过。
"""

from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.common.exceptions import BusinessException
from app.models.labs import Lab
from app.models.reservations import Reservation
from app.models.users import User
from app.schemas.reservation import ReservationCreateRequest, ReservationReviewRequest


def approved_conflict(
    db: Session, lab_id: int, date, start: str, end: str, exclude_id: int | None = None
) -> bool:
    """该实验室在这一天、这个时段是否已有「已通过」的预约

    时间段重叠的判定用的是 start < end AND end > start 这种半开区间比较，
    exclude_id 用在审核场景：判断"除自己之外"还有没有别的通过记录。

    原本放在 api/reservation.py，管理端审核接口要跨模块 import 它，
    现在移到 service 层，api 之间不再互相依赖。
    """
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


def create_reservation(
    db: Session, current_user: User, data: ReservationCreateRequest
) -> Reservation:
    """提交预约申请"""
    now = datetime.now()
    starts_at = datetime.combine(data.date, datetime.strptime(data.start, "%H:%M").time())
    if starts_at < now + timedelta(hours=2):
        raise BusinessException(message="预约需至少提前 2 小时提交")

    # 审核也锁同一间实验室，避免提交与审核同时进行时遗漏时段冲突。
    lab = db.query(Lab).filter(Lab.id == data.lab_id).with_for_update().first()
    if not lab:
        raise BusinessException(code=404, message="学习空间不存在")
    if lab.status == "maintenance":
        raise BusinessException(message="学习空间维护中，暂不可预约")
    if data.people > lab.capacity:
        raise BusinessException(message=f"预约人数不能超过空间容量 {lab.capacity} 人")
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
    return reservation


def list_my_reservations(db: Session, current_user: User) -> list[Reservation]:
    """当前用户的预约列表（新的在前）

    joinedload 把实验室和申请人一起带出来：响应体里要 lab_name/lab_code/
    applicant_name，不预加载的话每条记录都会再查两次库（N+1）。
    """
    return (
        db.query(Reservation)
        .options(joinedload(Reservation.lab), joinedload(Reservation.applicant))
        .filter(Reservation.applicant_id == current_user.id)
        .order_by(Reservation.create_time.desc(), Reservation.id.desc())
        .all()
    )


def cancel_reservation(
    db: Session, current_user: User, reservation_id: int
) -> Reservation:
    """取消自己的预约

    别人的预约一律按"不存在"处理（404），不用 403：
    返回 403 等于承认"这条记录存在，只是不归你"，能被拿来探测别人的预约 id。
    """
    existing = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not existing or existing.applicant_id != current_user.id:
        raise BusinessException(code=404, message="预约不存在")

    # 与提交、审核用同一把锁，避免取消的同时另一个请求正在判断冲突
    db.query(Lab).filter(Lab.id == existing.lab_id).with_for_update().first()
    # populate_existing 强制丢弃 session 里的旧对象，重新从库里读最新状态
    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == reservation_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if reservation.status not in ("pending", "approved"):
        raise BusinessException(code=409, message="当前状态不能取消预约")
    starts_at = datetime.combine(
        reservation.date, datetime.strptime(reservation.start, "%H:%M").time()
    )
    if starts_at < datetime.now() + timedelta(hours=2):
        raise BusinessException(code=409, message="预约开始前 2 小时内不能取消")
    reservation.status = "cancelled"
    db.commit()
    db.refresh(reservation)
    return reservation


def list_reservations_page(
    db: Session,
    page: int,
    page_size: int,
    status: str | None,
    keyword: str | None,
) -> tuple[int, list[Reservation]]:
    """分页查询预约（管理端），返回 (总数, 当前页数据)"""
    query = db.query(Reservation).join(Reservation.lab).join(Reservation.applicant)
    if status:
        if status not in ("pending", "approved", "rejected", "cancelled"):
            raise BusinessException(message="无效的预约状态")
        query = query.filter(Reservation.status == status)
    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        query = query.filter(
            or_(Lab.name.like(pattern), Lab.code.like(pattern), User.name.like(pattern))
        )
    total = query.count()
    items = (
        query.order_by(Reservation.create_time.desc(), Reservation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items


def review_reservation(
    db: Session, current_admin: User, reservation_id: int, data: ReservationReviewRequest
) -> Reservation:
    """审核预约（通过 / 驳回）

    通过时要重新校验一遍：距离审核通过可能已经过了很久，实验室可能被改成
    维护中、容量可能被调小、时段也可能被别的预约占掉。驳回则不需要这些检查。
    """
    existing = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not existing:
        raise BusinessException(code=404, message="预约不存在")

    # 同一实验室的审核按顺序处理，防止并发通过重叠时段。
    lab = db.query(Lab).filter(Lab.id == existing.lab_id).with_for_update().first()
    reservation = (
        db.query(Reservation)
        .filter(Reservation.id == reservation_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if reservation.status != "pending":
        raise BusinessException(code=409, message="该预约已处理，不能重复审核")
    if data.status == "approved":
        now = datetime.now()
        if (reservation.date, reservation.start) <= (now.date(), now.strftime("%H:%M")):
            raise BusinessException(code=409, message="预约时间已过，不能通过")
        if lab.status == "maintenance":
            raise BusinessException(code=409, message="学习空间维护中，不能通过预约")
        if reservation.people > lab.capacity:
            raise BusinessException(code=409, message="预约人数超过当前空间容量")
        if approved_conflict(
            db,
            reservation.lab_id,
            reservation.date,
            reservation.start,
            reservation.end,
            exclude_id=reservation.id,
        ):
            raise BusinessException(code=409, message="该时段已有通过的预约")

    reservation.status = data.status
    reservation.review_note = data.review_note.strip() if data.review_note else None
    reservation.reviewer_id = current_admin.id
    reservation.reviewed_at = datetime.now()
    db.commit()
    db.refresh(reservation)
    return reservation
