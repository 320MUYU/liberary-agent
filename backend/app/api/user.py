from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.users import User
from app.dependencies.auth import get_current_user
from app.schemas.user import UserResponse, UserUpdateRequest
from app.common.response import Response

router = APIRouter(prefix="/user", tags=["用户信息接口"])


@router.get("/info")
# 获取用户信息
def get_user_info(current_user: User = Depends(get_current_user)):
    return Response.success(data=UserResponse.model_validate(current_user))


@router.put("/info")
def update_user_info(
    data: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改当前登录用户的个人信息

    只更新姓名、邮箱、手机号、头像四个字段；账号 / 角色 / 状态不在这里改。
    说明：get_current_user 和这里都 Depends(get_db)，FastAPI 对同一个依赖
    默认做缓存，所以 current_user 拿到的对象和这里的 db 是同一个 session，
    直接 db.commit() 就能把改动落库。
    """
    current_user.name = data.name
    current_user.email = data.email
    current_user.phone = data.phone
    current_user.avatar = data.avatar

    db.commit()
    db.refresh(current_user)

    return Response.success(
        message="修改成功", data=UserResponse.model_validate(current_user)
    )