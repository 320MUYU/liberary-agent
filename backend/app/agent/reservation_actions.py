"""Confirmed space applications; action completion and business write are atomic."""

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from app.common.exceptions import BusinessException
from app.models.agent import AgentReservationAction
from app.models.reservations import Reservation
from app.models.users import User
from app.schemas.reservation import ReservationCreateRequest, reservation_response
from app.services import reservation_service
from app.services.space_discovery import room_snapshot


def draft_action(user_id, run_id, conditions):
    return AgentReservationAction(action_id=str(uuid5(NAMESPACE_URL, "space-reservation:" + run_id)),
        run_id=run_id, user_id=user_id, conditions=conditions.model_dump(mode="json"),
        status="draft", snapshot={}, expires_at=datetime.now() + timedelta(hours=24))


def lock_reader(db, user_id):
    user = db.query(User).filter_by(id=user_id).populate_existing().with_for_update().first()
    if user is None or user.status != 1:
        raise BusinessException("账号不可用", 403)
    return user


def preview(action):
    return {"id": action.action_id, "action_type": "reservation", "space": action.snapshot,
        "conditions": action.conditions, "expires_at": action.expires_at.isoformat(),
        "message": "确认后提交空间预约申请，等待管理员审核；当前检查结果不锁定时段。"}


def prepare_reservation(db, user_id, run_id, space_id, conditions):
    with reservation_service.write_transaction(db):
        lock_reader(db, user_id)
        action = db.query(AgentReservationAction).filter_by(run_id=run_id).populate_existing().with_for_update().first()
        if action is None:
            action = draft_action(user_id, run_id, conditions)
            db.add(action)
        if action.user_id != user_id or action.conditions != conditions.model_dump(mode="json"):
            raise BusinessException("预约条件不匹配，请重新查询", 409)
        if action.status != "draft":
            if action.lab_id != space_id:
                raise BusinessException("预约空间不匹配", 409)
            return preview(action)
        lab = reservation_service.lock_space(db, space_id)
        data = ReservationCreateRequest(lab_id=space_id, **action.conditions)
        reservation_service.validate_reservation(db, lab, data)
        action.lab_id = space_id
        action.snapshot = room_snapshot(lab)
        action.status = "prepared"
        action.expires_at = datetime.now() + timedelta(minutes=10)
        db.flush()
        db.refresh(action, with_for_update=True)
        result = preview(action)
    return result


def receipt(db, user_id, reservation_id, *, locked=False):
    query = db.query(Reservation).filter_by(id=reservation_id, applicant_id=user_id).populate_existing()
    reservation = (query.with_for_update() if locked else query).first()
    if reservation is None:
        raise BusinessException("预约不存在", 404)
    data = reservation_response(reservation).model_dump(mode="json", exclude={"applicant_id", "applicant_name"})
    messages = {"pending": "预约申请已提交，待管理员审核；尚未锁定时段。", "approved": "管理员已通过预约。",
        "rejected": "管理员已驳回预约，请查看审核说明。", "cancelled": "预约已取消。"}
    return {"status": "reservation_" + reservation.status, "reservation_id": reservation.id,
        "reservation": data, "message": messages[reservation.status]}


def decide_reservation(db, user_id, action_id, confirmed):
    if type(confirmed) is not bool:
        raise BusinessException("确认参数无效", 422)
    with reservation_service.write_transaction(db):
        user = lock_reader(db, user_id)
        action = db.query(AgentReservationAction).filter_by(action_id=action_id, user_id=user_id).populate_existing().with_for_update().first()
        if action is None or action.status == "draft":
            raise BusinessException("预约确认操作不存在", 404)
        if action.status == "completed":
            if not confirmed:
                raise BusinessException("预约已提交，请到我的预约中处理", 409)
            return receipt(db, user_id, action.reservation_id, locked=True)
        if action.status == "cancelled":
            if confirmed:
                raise BusinessException("操作已取消，请重新查询", 409)
            return {"status": "cancelled", "message": "已取消本次操作，没有提交预约。"}
        if not confirmed:
            action.status = "cancelled"
            return {"status": "cancelled", "message": "已取消本次操作，没有提交预约。"}
        if action.expires_at <= datetime.now():
            raise BusinessException("确认已过期，请重新查询", 409)
        lab = reservation_service.lock_space(db, action.lab_id)
        if room_snapshot(lab) != action.snapshot:
            raise BusinessException("空间信息已变化，请重新查询并确认", 409)
        data = ReservationCreateRequest(lab_id=lab.id, **action.conditions)
        # Pages and Agent tasks share the same locked deduplication and validation.
        reservation = reservation_service.create_reservation_in_transaction(db, user, data)
        action.reservation_id = reservation.id
        action.status = "completed"
        db.flush()
        db.refresh(reservation, with_for_update=True)
        result = receipt(db, user_id, reservation.id, locked=True)
    return result
