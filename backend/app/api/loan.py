from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin, get_current_user
from app.models.users import User
from app.schemas.loan import BorrowConfirmRequest, LoanPageResponse, LoanRejectRequest, LoanRequest
from app.services import loan_service


router = APIRouter(tags=["实体图书借还"])


@router.get("/loans")
def my_loans(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status: str | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    total, items = loan_service.list_my_loans(db, current_user, page, page_size, status)
    return Response.success(data=LoanPageResponse(total=total, page=page, page_size=page_size, items=items))


@router.post("/loans")
def apply_loan(
    data: LoanRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    loan = loan_service.create_loan(db, current_user, data)
    return Response.success(message="借阅申请已提交", data=loan_service.loan_response(db, loan))


@router.post("/loans/{loan_id}/cancel")
def cancel_loan(
    loan_id: int = Path(gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    loan = loan_service.cancel_loan(db, current_user, loan_id)
    return Response.success(message="借阅申请已取消", data=loan_service.loan_response(db, loan))


@router.post("/loans/{loan_id}/request-return")
def request_return(
    loan_id: int = Path(gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    loan = loan_service.request_return(db, current_user, loan_id)
    return Response.success(message="归还申请已提交，请交还实体图书并等待管理员确认", data=loan_service.loan_response(db, loan))


@router.get("/admin/loans")
def admin_loans(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    status: str | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=255),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    total, items = loan_service.list_loans_page(db, page, page_size, status, keyword)
    return Response.success(data=LoanPageResponse(total=total, page=page, page_size=page_size, items=items))


@router.post("/admin/loans/{loan_id}/confirm-borrow")
def confirm_borrow(
    data: BorrowConfirmRequest,
    loan_id: int = Path(gt=0),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    loan = loan_service.confirm_borrow(db, current_admin, loan_id, data)
    return Response.success(message="已确认借出", data=loan_service.loan_response(db, loan))


@router.post("/admin/loans/{loan_id}/reject")
def reject_loan(
    data: LoanRejectRequest,
    loan_id: int = Path(gt=0),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    loan = loan_service.reject_loan(db, current_admin, loan_id, data)
    return Response.success(message="借阅申请已拒绝", data=loan_service.loan_response(db, loan))


@router.post("/admin/loans/{loan_id}/confirm-return")
def confirm_return(
    loan_id: int = Path(gt=0),
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    loan = loan_service.confirm_return(db, current_admin, loan_id)
    return Response.success(message="已确认归还，副本恢复可借", data=loan_service.loan_response(db, loan))
