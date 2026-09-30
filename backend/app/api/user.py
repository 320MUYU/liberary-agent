from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.users import User
from app.schemas.user import PasswordUpdateRequest, UserResponse, UserUpdateRequest
from app.services import user_service

router = APIRouter(prefix="/user", tags=["用户信息接口"])


@router.get("/info")
def get_user_info(current_user: User = Depends(get_current_user)):
    """获取当前登录用户的信息"""
    return Response.success(data=UserResponse.model_validate(current_user))


@router.put("/info")
def update_user_info(
    data: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改当前登录用户的个人信息

    说明：get_current_user 和这里都 Depends(get_db)，FastAPI 对同一个依赖
    默认做缓存，所以 current_user 拿到的对象和这里的 db 是同一个 session，
    service 里直接 db.commit() 就能把改动落库。
    """
    user = user_service.update_profile(db, current_user, data)
    return Response.success(message="修改成功", data=UserResponse.model_validate(user))


@router.put("/password")
def update_password(
    data: PasswordUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改当前登录用户的密码

    为什么要验原密码、为什么这里能提示"原密码错误"而登录接口不能，
    理由写在 user_service.update_password 里。
    """
    user_service.update_password(db, current_user, data)
    return Response.success(message="密码修改成功，请重新登录")
