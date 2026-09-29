from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.common.response import Response
from app.database import get_db
from app.models.labs import Lab
from app.models.users import User
from app.dependencies.auth import get_current_user
from app.schemas.lab import LabResponse

router = APIRouter(prefix="/lab", tags=["实验室接口"])


@router.get("/list")
def list_labs(
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """实验室列表（登录后即可查看）

    这里故意不分页：实验室是数量有限的几十间，而且学生端本来就要
    一次拿到全部再在浏览器里按类别/状态筛选（和"用户列表"那种会持续增长的
    数据是两回事）。真到了几百间再改成按需查询也不迟。

    需要登录但不要求管理员：这是学生端页面要用的接口。
    """
    # Lab 上的 equipments 用了 lazy="selectin"，所以这里一次查询就能
    # 把每间实验室的设备一起带出来，不会出现 N+1
    labs = db.query(Lab).order_by(Lab.code).all()

    return Response.success(data=[LabResponse.model_validate(lab) for lab in labs])


@router.get("/{lab_id}")
def get_lab(
    lab_id: int,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """实验室详情"""
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise BusinessException(code=404, message="实验室不存在")

    return Response.success(data=LabResponse.model_validate(lab))
