from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin, get_current_user
from app.models.users import User
from app.schemas.book import (
    BookCopyCreateRequest,
    BookCopyPageResponse,
    BookCopyResponse,
    BookCopyUpdateRequest,
    BookCreateRequest,
    BookPageResponse,
    BookUpdateRequest,
)
from app.services import book_service


router = APIRouter(tags=["实体图书接口"])


@router.get("/books")
def list_books(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    keyword: str | None = Query(None, max_length=255),
    category: str | None = Query(None, max_length=100),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total, items = book_service.list_books_page(db, page, page_size, keyword, category)
    return Response.success(
        data=BookPageResponse(total=total, page=page, page_size=page_size, items=items)
    )


@router.get("/books/{book_id}")
def get_book(
    book_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return Response.success(data=book_service.get_book_detail(db, book_id))


@router.get("/admin/books")
def admin_list_books(
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    keyword: str | None = Query(None, max_length=255),
    category: str | None = Query(None, max_length=100),
    is_active: bool | None = Query(None),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    total, items = book_service.list_books_page(
        db, page, page_size, keyword, category, is_active=is_active
    )
    return Response.success(
        data=BookPageResponse(total=total, page=page, page_size=page_size, items=items)
    )


@router.post("/admin/books")
def create_book(
    data: BookCreateRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    book = book_service.create_book(db, data)
    return Response.success(message="书目已创建", data=book_service.book_response(db, book))


@router.put("/admin/books/{book_id}")
def update_book(
    book_id: int,
    data: BookUpdateRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    book = book_service.update_book(db, book_id, data)
    return Response.success(message="书目已更新", data=book_service.book_response(db, book))


@router.get("/admin/books/{book_id}/copies")
def list_book_copies(
    book_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    total, items = book_service.list_book_copies_page(db, book_id, page, page_size)
    return Response.success(
        data=BookCopyPageResponse(total=total, page=page, page_size=page_size, items=items)
    )


@router.post("/admin/book-copies")
def create_book_copy(
    data: BookCopyCreateRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    copy = book_service.create_book_copy(db, data)
    return Response.success(message="馆藏副本已创建", data=BookCopyResponse.model_validate(copy))


@router.put("/admin/book-copies/{copy_id}")
def update_book_copy(
    copy_id: int,
    data: BookCopyUpdateRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    copy = book_service.update_book_copy(db, copy_id, data)
    return Response.success(message="馆藏副本已更新", data=BookCopyResponse.model_validate(copy))
