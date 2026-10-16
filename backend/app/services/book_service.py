"""图书书目和实体副本管理，库存始终从馆藏状态计算。"""

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.models.book_copies import BookCopy
from app.models.books import Book
from app.models.book_sources import BookSource
from app.models.loans import Loan
from app.schemas.book import (
    BookCopyCreateRequest,
    BookCopyResponse,
    BookCopyUpdateRequest,
    BookCreateRequest,
    BookResponse,
    BookUpdateRequest,
    BookSourceResponse,
)


def get_book_or_404(
    db: Session, book_id: int, active_only: bool = False, for_update: bool = False
) -> Book:
    query = db.query(Book).filter(Book.id == book_id)
    if active_only:
        query = query.filter(Book.is_active.is_(True))
    if for_update:
        query = query.populate_existing().with_for_update()
    book = query.first()
    if book is None:
        raise BusinessException(code=404, message="图书不存在或已下架")
    return book


def _inventory(db: Session, book_ids: list[int]) -> dict[int, tuple[int, int]]:
    if not book_ids:
        return {}
    occupied = select(Loan.id).where(Loan.active_copy_id == BookCopy.id).exists()
    rows = (
        db.query(
            BookCopy.book_id,
            func.count(BookCopy.id),
            func.sum(case((and_(BookCopy.status == "available", ~occupied), 1), else_=0)),
        )
        .filter(BookCopy.book_id.in_(book_ids), BookCopy.status != "withdrawn")
        .group_by(BookCopy.book_id)
        .all()
    )
    return {book_id: (total, available) for book_id, total, available in rows}


def _response(book: Book, counts: tuple[int, int], source: BookSource | None = None) -> BookResponse:
    response = BookResponse.model_validate(book)
    response.total_copies = int(counts[0])
    # MySQL SUM(integer) returns Decimal; assignment does not revalidate Pydantic fields.
    response.available_copies = int(counts[1]) if book.is_active else 0
    if source:
        response.source = BookSourceResponse(url=source.source_url,
            languages=source.metadata_json.get("languages", []))
    return response


def book_response(db: Session, book: Book) -> BookResponse:
    source = db.scalar(select(BookSource).where(BookSource.book_id == book.id))
    return _response(book, _inventory(db, [book.id]).get(book.id, (0, 0)), source)


def get_book_detail(
    db: Session, book_id: int, active_only: bool = True
) -> BookResponse:
    return book_response(db, get_book_or_404(db, book_id, active_only=active_only))


def list_books_page(
    db: Session,
    page: int,
    page_size: int,
    keyword: str | None = None,
    category: str | None = None,
    is_active: bool | None = True,
) -> tuple[int, list[BookResponse]]:
    query = db.query(Book)
    if is_active is not None:
        query = query.filter(Book.is_active.is_(is_active))
    if keyword and keyword.strip():
        value = keyword.strip()
        query = query.filter(
            or_(
                Book.title.contains(value, autoescape=True),
                Book.author.contains(value, autoescape=True),
                Book.isbn.contains(value, autoescape=True),
            )
        )
    if category and category.strip():
        query = query.filter(Book.category == category.strip())
    total = query.count()
    books = query.order_by(Book.id).offset((page - 1) * page_size).limit(page_size).all()
    counts = _inventory(db, [book.id for book in books])
    sources = {source.book_id: source for source in db.scalars(
        select(BookSource).where(BookSource.book_id.in_([book.id for book in books])))} if books else {}
    return total, [_response(book, counts.get(book.id, (0, 0)), sources.get(book.id)) for book in books]


def _ensure_isbn_available(
    db: Session, isbn: str | None, exclude_book_id: int | None = None
) -> None:
    if isbn is None:
        return
    query = db.query(Book.id).filter(Book.isbn == isbn)
    if exclude_book_id is not None:
        query = query.filter(Book.id != exclude_book_id)
    if query.first():
        raise BusinessException(code=409, message="ISBN 已被其他书目使用")


def _save(db: Session, item: Book | BookCopy, conflict_message: str):
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except IntegrityError as exc:
        db.rollback()
        raise BusinessException(code=409, message=conflict_message) from exc
    return item


def create_book(db: Session, data: BookCreateRequest) -> Book:
    _ensure_isbn_available(db, data.isbn)
    return _save(db, Book(**data.model_dump()), "ISBN 已被其他书目使用")


def update_book(db: Session, book_id: int, data: BookUpdateRequest) -> Book:
    book = get_book_or_404(db, book_id, for_update=True)
    _ensure_isbn_available(db, data.isbn, exclude_book_id=book_id)
    for field, value in data.model_dump().items():
        setattr(book, field, value)
    return _save(db, book, "ISBN 已被其他书目使用")


def list_book_copies_page(
    db: Session, book_id: int, page: int, page_size: int
) -> tuple[int, list[BookCopyResponse]]:
    get_book_or_404(db, book_id)
    query = db.query(BookCopy).filter(BookCopy.book_id == book_id)
    total = query.count()
    items = query.order_by(BookCopy.id).offset((page - 1) * page_size).limit(page_size).all()
    occupied = set(db.scalars(select(Loan.active_copy_id).where(
        Loan.active_copy_id.in_([item.id for item in items])
    )))
    responses = []
    for item in items:
        response = BookCopyResponse.model_validate(item)
        response.is_on_loan = item.id in occupied
        responses.append(response)
    return total, responses


def _ensure_barcode_available(
    db: Session, barcode: str, exclude_copy_id: int | None = None
) -> None:
    query = db.query(BookCopy.id).filter(BookCopy.barcode == barcode)
    if exclude_copy_id is not None:
        query = query.filter(BookCopy.id != exclude_copy_id)
    if query.first():
        raise BusinessException(code=409, message="馆藏条码已被其他副本使用")


def create_book_copy(db: Session, data: BookCopyCreateRequest) -> BookCopy:
    get_book_or_404(db, data.book_id, for_update=True)
    _ensure_barcode_available(db, data.barcode)
    return _save(db, BookCopy(**data.model_dump()), "馆藏条码已被其他副本使用")


def update_book_copy(
    db: Session, copy_id: int, data: BookCopyUpdateRequest
) -> BookCopy:
    book_id = db.query(BookCopy.book_id).filter(BookCopy.id == copy_id).scalar()
    if book_id is None:
        raise BusinessException(code=404, message="馆藏副本不存在")
    # 全部库存变更先锁书目、再锁副本，借阅业务可复用同一锁顺序。
    get_book_or_404(db, book_id, for_update=True)
    copy = (
        db.query(BookCopy)
        .filter(BookCopy.id == copy_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if copy is None:
        raise BusinessException(code=404, message="馆藏副本不存在")
    # 取得书目和副本锁后使用当前读，避免 MySQL 的早期快照漏掉刚确认的借阅。
    occupied = db.query(Loan.id).filter(Loan.active_copy_id == copy_id).with_for_update(read=True).first()
    if occupied:
        db.rollback()
        raise BusinessException(code=409, message="副本正在借阅或等待归还确认，暂不能修改")
    _ensure_barcode_available(db, data.barcode, exclude_copy_id=copy_id)
    for field, value in data.model_dump().items():
        setattr(copy, field, value)
    return _save(db, copy, "馆藏条码已被其他副本使用")
