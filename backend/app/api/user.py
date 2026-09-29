from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.users import User
from app.dependencies.auth import get_current_user
from app.schemas.user import PasswordUpdateRequest, UserResponse, UserUpdateRequest
from app.utils.bcrypt import hash_password, verify_password
from app.common.response import Response
from app.common.exceptions import BusinessException

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


@router.put("/password")
def update_password(
    data: PasswordUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改当前登录用户的密码

    为什么有 token 还要验原密码：token 只能证明"请求来自某个已登录的账号"，
    不证明"操作的人就是本人"。如果凭 token 就能直接改密码，那么 token 一旦泄露
    （浏览器缓存、XSS、共享设备忘记退出），对方可以改掉密码把账号彻底夺走。
    加上原密码，等于把门槛重新抬回"知道密码"，同时也能挡掉被劫持的登录态。

    和登录接口不同，这里可以明确提示"原密码错误"：请求方本来就已登录，
    这句话泄露不了新信息；登录接口不能这么提示，否则等于告诉攻击者账号是否存在。

    "两次输入不一致""新旧密码相同"已在 PasswordUpdateRequest 里拦掉了（走 422），
    这里只剩必须查库才能判断的"原密码是否正确"。
    """
    if not verify_password(data.old_password, current_user.password):
        raise BusinessException(message="原密码错误")

    # 存进库的依然是 bcrypt 密文，明文密码不落库、也不写日志
    current_user.password = hash_password(data.new_password)
    db.commit()

    return Response.success(message="密码修改成功，请重新登录")
