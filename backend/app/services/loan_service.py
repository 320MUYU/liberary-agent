"""实体图书借还；修改操作按读者、书目、申请、副本的顺序加锁。"""

from contextlib import contextmanager
from datetime import datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.config import settings
from app.models.book_copies import BookCopy
from app.models.books import Book
from app.models.loans import Loan
from app.models.users import User
from app.schemas.loan import BorrowConfirmRequest, LoanRejectRequest, LoanRequest, LoanResponse
from app.services.notification_service import emit_notification


LOAN_STATUSES = {"pending", "borrowed", "return_pending", "returned", "rejected", "cancelled"}
ACTIVE_STATUSES = ("borrowed", "return_pending")


@contextmanager
def _write_transaction(db: Session):
    """业务校验失败也回滚，及时释放已获取的行锁。"""
    try:
        yield
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise BusinessException("借阅记录已发生变化，请刷新后重试", 409) from exc
    except OperationalError as exc:
        db.rollback()
        # 只把已知 MySQL 并发锁冲突转换为可重试的业务状态。
        # 连接中断、SQL 错误等仍原样抛出，不能伪装成普通业务冲突。
        if exc.orig.args and exc.orig.args[0] in (1213, 1205):
            raise BusinessException("借阅操作发生并发冲突，请刷新后重试", 409) from exc
        raise
    except Exception:
        db.rollback()
        raise


def _lock_reader(db: Session, reader_id: int) -> User:
    reader = (
        db.query(User).filter(User.id == reader_id)
        .populate_existing().with_for_update().first()
    )
    if reader is None:
        raise BusinessException("读者不存在", 404)
    return reader


def _lock_book(db: Session, book_id: int) -> Book:
    book = (
        db.query(Book).filter(Book.id == book_id)
        .populate_existing().with_for_update().first()
    )
    if book is None:
        raise BusinessException("图书不存在", 404)
    return book


def _lock_loan(db: Session, loan_id: int, reader_id: int | None = None):
    # 先只读不可变的关联 ID，随后按固定顺序取锁，并重新读取状态。
    query = db.query(Loan.reader_id, Loan.book_id).filter(Loan.id == loan_id)
    if reader_id is not None:
        query = query.filter(Loan.reader_id == reader_id)
    identifiers = query.first()
    if identifiers is None:
        raise BusinessException("借阅记录不存在", 404)
    reader = _lock_reader(db, identifiers.reader_id)
    book = _lock_book(db, identifiers.book_id)
    loan = (
        db.query(Loan).filter(Loan.id == loan_id)
        .populate_existing().with_for_update().first()
    )
    if loan is None or (reader_id is not None and loan.reader_id != reader_id):
        raise BusinessException("借阅记录不存在", 404)
    return reader, book, loan


def _available_copy(db: Session, book_id: int, copy_id: int | None = None):
    query = db.query(BookCopy).filter(
        BookCopy.book_id == book_id, BookCopy.status == "available"
    )
    if copy_id is not None:
        query = query.filter(BookCopy.id == copy_id)
    copies = query.order_by(BookCopy.id).populate_existing().with_for_update().all()
    for copy in copies:
        # MySQL 默认可重复读下也需要锁定读，避免沿用鉴权时建立的旧快照。
        occupied = (
            db.query(Loan.id).filter(Loan.active_copy_id == copy.id)
            .with_for_update(read=True).first()
        )
        if occupied is None:
            return copy
    return None


def _require_status(loan: Loan, expected: str):
    if loan.status != expected:
        raise BusinessException("当前借阅状态不允许此操作，请刷新后重试", 409)


def create_loan_in_transaction(db: Session, current_user: User, book_id: int) -> Loan:
    """Caller owns commit/rollback, allowing an action receipt to commit atomically."""
    reader = _lock_reader(db, current_user.id)
    if reader.status != 1:
        raise BusinessException("读者账号已停用", 409)
    book = _lock_book(db, book_id)
    if not book.is_active:
        raise BusinessException("图书不存在或已下架", 404)
    duplicate = (
        db.query(Loan.id).filter(
            Loan.reader_id == reader.id, Loan.open_book_id == book.id
        ).with_for_update().first()
    )
    if duplicate:
        raise BusinessException("已有该图书的未完成借阅，请勿重复申请", 409)
    if _available_copy(db, book.id) is None:
        raise BusinessException("该图书暂无可借副本", 409)
    loan = Loan(book_id=book.id, reader_id=reader.id, status="pending", open_book_id=book.id)
    db.add(loan)
    db.flush()
    return loan


def create_loan(db: Session, current_user: User, data: LoanRequest) -> Loan:
    with _write_transaction(db):
        loan = create_loan_in_transaction(db, current_user, data.book_id)
    db.refresh(loan)
    return loan


def cancel_loan(db: Session, current_user: User, loan_id: int) -> Loan:
    with _write_transaction(db):
        _, _, loan = _lock_loan(db, loan_id, current_user.id)
        _require_status(loan, "pending")
        loan.status = "cancelled"
        loan.open_book_id = None
    db.refresh(loan)
    return loan


def confirm_borrow(
    db: Session, current_admin: User, loan_id: int, data: BorrowConfirmRequest
) -> Loan:
    with _write_transaction(db):
        reader, book, loan = _lock_loan(db, loan_id)
        _require_status(loan, "pending")
        if reader.status != 1:
            raise BusinessException("读者账号已停用，不能确认借出", 409)
        if not book.is_active:
            raise BusinessException("图书已下架，不能确认借出", 409)
        # 先锁读者行，让该读者不同书目的并发确认也串行检查借阅上限。
        active_loans = (
            db.query(Loan.id).filter(
                Loan.reader_id == reader.id, Loan.status.in_(ACTIVE_STATUSES)
            ).with_for_update(read=True).all()
        )
        if len(active_loans) >= settings.BOOK_MAX_ACTIVE_LOANS:
            raise BusinessException(f"每人最多同时借阅 {settings.BOOK_MAX_ACTIVE_LOANS} 本图书", 409)
        copy = _available_copy(db, book.id, data.copy_id)
        if copy is None:
            raise BusinessException("所选副本不可借或该图书暂无可借副本", 409)
        now = datetime.now()
        loan.status = "borrowed"
        loan.copy_id = copy.id
        loan.active_copy_id = copy.id
        loan.borrowed_at = now
        loan.due_at = now + timedelta(days=settings.BOOK_LOAN_DAYS)
        loan.borrowed_by = current_admin.id
        loan.reviewed_by = current_admin.id
        emit_notification(db, user_id=reader.id, event_key=f"loan:{loan.id}:borrowed",
            kind="loan_borrowed", title="已确认借出", resource_type="loan", resource_id=loan.id,
            content=f"《{book.title}》已确认借出，请于 {loan.due_at:%Y-%m-%d %H:%M} 前归还。")
    db.refresh(loan)
    return loan


def reject_loan(
    db: Session, current_admin: User, loan_id: int, data: LoanRejectRequest
) -> Loan:
    with _write_transaction(db):
        reader, book, loan = _lock_loan(db, loan_id)
        _require_status(loan, "pending")
        loan.status = "rejected"
        loan.open_book_id = None
        loan.reject_reason = data.reason
        loan.reviewed_by = current_admin.id
        emit_notification(db, user_id=reader.id, event_key=f"loan:{loan.id}:rejected",
            kind="loan_rejected", title="借阅申请已驳回", resource_type="loan", resource_id=loan.id,
            content=f"《{book.title}》的借阅申请已驳回。原因：{data.reason}")
    db.refresh(loan)
    return loan


def request_return_in_transaction(db: Session, current_user: User, loan_id: int) -> Loan:
    """Caller owns commit/rollback so Agent receipt and return change are atomic."""
    _, _, loan = _lock_loan(db, loan_id, current_user.id)
    _require_status(loan, "borrowed")
    loan.status = "return_pending"
    loan.return_requested_at = datetime.now()
    db.flush()
    return loan


def request_return(db: Session, current_user: User, loan_id: int) -> Loan:
    with _write_transaction(db):
        loan = request_return_in_transaction(db, current_user, loan_id)
    db.refresh(loan)
    return loan


def confirm_return(db: Session, current_admin: User, loan_id: int) -> Loan:
    with _write_transaction(db):
        reader, book, loan = _lock_loan(db, loan_id)
        _require_status(loan, "return_pending")
        db.query(BookCopy).filter(BookCopy.id == loan.copy_id).with_for_update().first()
        loan.status = "returned"
        loan.active_copy_id = None
        loan.open_book_id = None
        loan.returned_at = datetime.now()
        loan.returned_by = current_admin.id
        emit_notification(db, user_id=reader.id, event_key=f"loan:{loan.id}:returned",
            kind="loan_returned", title="已确认归还", resource_type="loan", resource_id=loan.id,
            content=f"《{book.title}》已确认归还，感谢按时交还图书。")
    db.refresh(loan)
    return loan


def _response_query(db: Session):
    return (
        db.query(Loan, Book, User, BookCopy)
        .join(Book, Book.id == Loan.book_id)
        .join(User, User.id == Loan.reader_id)
        .outerjoin(BookCopy, BookCopy.id == Loan.copy_id)
    )


def _row_response(row) -> LoanResponse:
    loan, book, reader, copy = row
    return LoanResponse(
        id=loan.id, book_id=book.id, book_title=book.title,
        reader_id=reader.id, reader_name=reader.name, reader_username=reader.username,
        status=loan.status, copy_id=loan.copy_id,
        barcode=copy.barcode if copy else None, location=copy.location if copy else None,
        borrowed_at=loan.borrowed_at, due_at=loan.due_at,
        return_requested_at=loan.return_requested_at, returned_at=loan.returned_at,
        reject_reason=loan.reject_reason, create_time=loan.create_time,
        is_overdue=bool(
            loan.status in ACTIVE_STATUSES and loan.due_at and loan.due_at < datetime.now()
        ),
    )


def loan_response(db: Session, loan: Loan) -> LoanResponse:
    return _row_response(_response_query(db).filter(Loan.id == loan.id).one())


def _page(query, page: int, page_size: int, status: str | None):
    if status is not None:
        if status not in LOAN_STATUSES:
            raise BusinessException("无效的借阅状态", 400)
        query = query.filter(Loan.status == status)
    total = query.count()
    rows = (
        query.order_by(Loan.create_time.desc(), Loan.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return total, [_row_response(row) for row in rows]


def list_my_loans(db: Session, current_user: User, page: int, page_size: int, status: str | None, keyword: str | None = None):
    query = _response_query(db).filter(Loan.reader_id == current_user.id)
    if keyword and keyword.strip():
        value = keyword.strip()
        query = query.filter(or_(Book.title.contains(value, autoescape=True),
            Book.author.contains(value, autoescape=True), Book.isbn.contains(value, autoescape=True)))
    return _page(query, page, page_size, status)


def get_my_loan(db: Session, current_user: User, loan_id: int):
    row = _response_query(db).filter(Loan.reader_id == current_user.id, Loan.id == loan_id).first()
    if row is None:
        raise BusinessException("借阅记录不存在", 404)
    return _row_response(row)


def list_loans_page(
    db: Session, page: int, page_size: int, status: str | None, keyword: str | None
):
    query = _response_query(db)
    if keyword and keyword.strip():
        value = keyword.strip()
        query = query.filter(or_(
            Book.title.contains(value, autoescape=True),
            User.name.contains(value, autoescape=True),
            User.username.contains(value, autoescape=True),
        ))
    return _page(query, page, page_size, status)
