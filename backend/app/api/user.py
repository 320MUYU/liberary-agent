from fastapi import APIRouter, Depends
from app.models.users import User
from app.dependencies.auth import get_current_user
from app.schemas.user import UserResponse
from app.common.response import Response

router = APIRouter(prefix="/user", tags=["用户信息接口"])


@router.get("/info")
# 获取用户信息
def get_user_info(current_user: User = Depends(get_current_user)):
    return Response.success(data=UserResponse.model_validate(current_user))