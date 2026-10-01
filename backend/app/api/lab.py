from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.users import User
from app.schemas.lab import LabResponse
from app.services import lab_service

router = APIRouter(prefix="/lab", tags=["学习空间接口"])


@router.get("/list")
def list_labs(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """学习空间列表（登录后即可查看）

    需要登录但不要求管理员：这是学生端页面要用的接口。
    为什么不分页、为什么不出现 N+1，见 lab_service.list_labs。
    """
    labs = lab_service.list_labs(db)

    return Response.success(data=[LabResponse.model_validate(lab) for lab in labs])


@router.get("/{lab_id}")
def get_lab(
    lab_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """学习空间详情"""
    lab = lab_service.get_lab_or_404(db, lab_id)

    return Response.success(data=LabResponse.model_validate(lab))
