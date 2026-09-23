from fastapi import APIRouter,Depends
from app.schemas.auth import  LoginRequest
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.users import User
from app.schemas.user import UserResponse
from app.utils.bcrypt import verify_password
from app.utils.jwt import decode_access_token,create_access_token

router=APIRouter(prefix="/auth",tags=["权限验证接口"])

@router.post("/login")
def login(data:LoginRequest,db:Session = Depends(get_db)):
    #根据用户账号查询数据库
    user=db.query(User).filter(User.username == data.username).first()

    # 判断密码和账号是否正确
    if not user or not verify_password(data.password, user.password):
        return {"code": 400, "message": "账号或密码错误"}

    #判断学生状态是否正常
    if user.status != 1:
        return {"code": 403, "message": "账号已被禁用"}
    #创建token
    token = create_access_token(user.id)
    #返回token和用户信息
    return {
        "code": 200,
        "message": "操作成功",
        "data": {"user":UserResponse.model_validate(user),"token":token}
        
    }