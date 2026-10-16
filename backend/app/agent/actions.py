"""Confirmation records and loan mutations share the business transaction."""

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from app.common.exceptions import BusinessException
from app.models.agent import AgentAction
from app.services import loan_service


def snapshot(book):
    return {key: getattr(book, key) for key in ("id", "title", "author", "isbn", "publisher", "publication_year")}


def preview(action):
    return {"id": action.action_id, "book": action.snapshot,
            "expires_at": action.expires_at.isoformat(),
            "message": "确认后提交借阅申请，等待管理员确认借出。申请不占库存，也不保证最终借出。"}


def prepare_borrow(db, user_id, run_id, book_id):
    with loan_service._write_transaction(db):
        reader = loan_service._lock_reader(db, user_id)
        if reader.status != 1:
            raise BusinessException("账号已停用", 403)
        existing = db.query(AgentAction).filter_by(run_id=run_id).with_for_update().first()
        if existing:
            if existing.user_id != user_id or existing.book_id != book_id or existing.action_type != "borrow":
                raise BusinessException("操作内容不匹配，请重新查找", 409)
            return preview(existing)
        book = loan_service._lock_book(db, book_id)
        if not book.is_active:
            raise BusinessException("图书已下架，请重新查找", 409)
        if loan_service._available_copy(db, book_id) is None:
            raise BusinessException("该书暂无可借副本，请重新查找", 409)
        action = AgentAction(action_id=str(uuid5(NAMESPACE_URL, "library-borrow:" + run_id)),
            run_id=run_id, user_id=user_id, book_id=book_id, snapshot=snapshot(book),
            status="prepared", expires_at=datetime.now() + timedelta(minutes=10))
        db.add(action)
        db.flush()
        result = preview(action)
    return result


def decide_borrow(db, user_id, action_id, confirmed):
    if type(confirmed) is not bool:
        raise BusinessException("确认参数无效", 422)
    with loan_service._write_transaction(db):
        reader = loan_service._lock_reader(db, user_id)
        if reader.status != 1:
            raise BusinessException("账号已停用", 403)
        action = db.query(AgentAction).filter_by(action_id=action_id, user_id=user_id).populate_existing().with_for_update().first()
        if action is None or action.action_type != "borrow":
            raise BusinessException("操作不存在", 404)
        if action.status == "completed":
            if not confirmed:
                raise BusinessException("申请已提交，请到我的借阅中取消", 409)
            return {"status": "pending", "loan_id": action.loan_id, "message": "借阅申请已提交，待管理员确认。可在我的借阅查看最新状态。"}
        if action.status == "cancelled":
            if confirmed:
                raise BusinessException("操作已取消，请重新查找", 409)
            return {"status": "cancelled", "message": "已取消本次操作，没有提交借阅申请。"}
        if not confirmed:
            action.status = "cancelled"
            return {"status": "cancelled", "message": "已取消本次操作，没有提交借阅申请。"}
        if action.expires_at <= datetime.now():
            raise BusinessException("确认已过期，请重新查找并确认", 409)
        book = loan_service._lock_book(db, action.book_id)
        if snapshot(book) != action.snapshot:
            raise BusinessException("书目信息已变化，请重新查找并确认", 409)
        loan = loan_service.create_loan_in_transaction(db, reader, action.book_id)
        action.loan_id = loan.id
        action.status = "completed"
        result = {"status": "pending", "loan_id": loan.id, "message": "借阅申请已提交，待管理员确认。可在我的借阅查看最新状态。"}
    return result


def return_snapshot(db, book, loan):
    data = loan_service.loan_response(db, loan).model_dump(mode="json")
    fields = ("id", "book_id", "book_title", "copy_id", "barcode", "borrowed_at", "due_at")
    return {"book": snapshot(book), "loan": {field: data[field] for field in fields}}


def return_preview(action):
    return {"id": action.action_id, "action_type": "return", **action.snapshot,
            "expires_at": action.expires_at.isoformat(),
            "message": "确认后提交归还申请，请交还实体图书并等待管理员确认；确认归还前仍占用副本。"}


def prepare_return(db, user_id, run_id, loan_id):
    with loan_service._write_transaction(db):
        reader, book, loan = loan_service._lock_loan(db, loan_id, user_id)
        if reader.status != 1:
            raise BusinessException("账号已停用", 403)
        existing = db.query(AgentAction).filter_by(run_id=run_id).populate_existing().with_for_update().first()
        if existing:
            if existing.user_id != user_id or existing.loan_id != loan_id or existing.action_type != "return":
                raise BusinessException("操作内容不匹配，请重新查询", 409)
            return return_preview(existing)
        loan_service._require_status(loan, "borrowed")
        action = AgentAction(action_id=str(uuid5(NAMESPACE_URL, "library-return:" + run_id)),
            run_id=run_id, user_id=user_id, book_id=book.id, loan_id=loan.id, action_type="return",
            snapshot=return_snapshot(db, book, loan), status="prepared",
            expires_at=datetime.now() + timedelta(minutes=10))
        db.add(action)
        db.flush()
        result = return_preview(action)
    return result


def return_receipt(db, loan):
    return {"status": loan.status, "loan_id": loan.id,
        "loan": loan_service.loan_response(db, loan).model_dump(mode="json"),
        "message": ("管理员已确认归还。" if loan.status == "returned" else
                    "归还申请已提交，请交还实体图书，待管理员确认归还。确认前仍计入借阅并占用副本。")}


def decide_return(db, user_id, action_id, confirmed):
    if type(confirmed) is not bool:
        raise BusinessException("确认参数无效", 422)
    with loan_service._write_transaction(db):
        reader = loan_service._lock_reader(db, user_id)
        if reader.status != 1:
            raise BusinessException("账号已停用", 403)
        # Reader lock serializes actions from this user's other tasks and business pages.
        action = db.query(AgentAction).filter_by(action_id=action_id, user_id=user_id).populate_existing().with_for_update().first()
        if action is None or action.action_type != "return":
            raise BusinessException("归还操作不存在", 404)
        if action.status == "cancelled":
            if confirmed:
                raise BusinessException("操作已取消，请重新查询", 409)
            return {"status": "cancelled", "message": "已取消本次操作，没有提交归还申请。"}
        if action.status == "completed" and not confirmed:
            raise BusinessException("归还申请已提交，请查看我的借阅", 409)
        if not confirmed:
            action.status = "cancelled"
            return {"status": "cancelled", "message": "已取消本次操作，没有提交归还申请。"}
        _, book, loan = loan_service._lock_loan(db, action.loan_id, user_id)
        if action.status == "completed":
            return return_receipt(db, loan)
        if action.expires_at <= datetime.now():
            raise BusinessException("确认已过期，请重新查询并确认", 409)
        if return_snapshot(db, book, loan) != action.snapshot:
            raise BusinessException("借阅信息已变化，请重新查询并确认", 409)
        # Another confirmed task or the existing loans page may already have submitted it.
        if loan.status not in {"return_pending", "returned"}:
            loan = loan_service.request_return_in_transaction(db, reader, loan.id)
        action.status = "completed"
        # Return database timestamp precision on the first response as well as replays.
        db.flush()
        db.refresh(loan, with_for_update=True)
        result = return_receipt(db, loan)
    return result
