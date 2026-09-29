from fastapi import Depends, HTTPException, status  
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session 

from app.database import get_db 
from app.models.users import User
from app.utils.jwt import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    try:
        payload = decode_access_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录"
        )
    # 获取到用户ID
    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的登录凭证"
        )
    # 从数据库根据用户ID查询用户信息
    user = db.query(User).filter(User.id == user_id).first()
    # 新增判断：防止用户为空，访问user.status时报错
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在"
        )
    if user.status != 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户被禁用"
        )
    return user


def get_current_admin(current_user: User = Depends(get_current_user)):
    """在"已登录"的基础上再要求管理员身份

    这里是管理员接口的唯一防线。前端把管理菜单藏起来只是体验问题，
    请求可以绕过页面直接发，所以每个管理接口都必须挂上这个依赖。

    返回 403 而不是 401：401 的语义是"没登录/登录失效"，前端拦截器收到 401
    会清掉登录态跳登录页；而"登录了但不是管理员"不该把用户踢下线。
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限"
        )
    return current_user
