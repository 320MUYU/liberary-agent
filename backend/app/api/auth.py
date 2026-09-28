from fastapi import APIRouter, Depends
from app.schemas.auth import LoginRequest
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.users import User
from app.schemas.user import UserResponse
from app.utils.bcrypt import verify_password
from app.utils.jwt import decode_access_token, create_access_token
from app.common.response import Response
from app.common.exceptions import BusinessException

router = APIRouter(prefix="/auth", tags=["权限验证接口"])


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    # 根据用户账号查询数据库
    user = db.query(User).filter(User.username == data.username).first()

    # 判断账号和密码是否正确
    if not user or not verify_password(data.password, user.password):
        raise BusinessException(message="账号或密码错误")

    # 验证账号的状态
    if user.status != 1:
        raise BusinessException(message="账号被禁用")

    # 创建token
    token = create_access_token(user.id)

    # 返回信息
    return Response.success(
        data={"token": token, "user": UserResponse.model_validate(user)}
    )