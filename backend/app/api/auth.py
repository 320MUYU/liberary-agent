from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.schemas.auth import LoginRequest, RegisterRequest
from app.schemas.user import UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["权限验证接口"])


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """登录：校验账号密码与状态，通过后签发 token"""
    user, token = auth_service.login(db, data.username, data.password)
    return Response.success(
        # UserResponse 里没有 password 字段，不会泄露密文
        data={"token": token, "user": UserResponse.model_validate(user)}
    )


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册

    注册成功后不签发 token，前端引导用户去登录页手动登录。
    role 与 status 在 service 里写死，不接受前端传参。
    """
    user = auth_service.register(db, data)
    return Response.success(
        message="注册成功，请登录", data=UserResponse.model_validate(user)
    )
