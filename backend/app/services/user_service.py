"""用户业务逻辑：个人信息维护 + 管理端用户管理

分层约定同 auth_service：只收 db 会话与入参，返回 ORM 对象。
管理端接口的"操作者不能是自己"这类规则也放在这里，
和数据库校验待在同一个函数里，路由层就不会漏掉。
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.models.users import User
from app.schemas.user import (
    PasswordUpdateRequest,
    UserUpdateRequest,
)
from app.utils.bcrypt import hash_password, verify_password


def update_profile(db: Session, user: User, data: UserUpdateRequest) -> User:
    """修改个人信息

    只更新姓名、邮箱、手机号、头像四个字段；账号 / 角色 / 状态不在这里改。
    """
    user.name = data.name
    user.email = data.email
    user.phone = data.phone
    user.avatar = data.avatar

    db.commit()
    db.refresh(user)
    return user


def update_password(db: Session, user: User, data: PasswordUpdateRequest) -> None:
    """修改密码

    为什么有 token 还要验原密码：token 只能证明"请求来自某个已登录的账号"，
    不证明"操作的人就是本人"。如果凭 token 就能直接改密码，那么 token 一旦泄露
    （浏览器缓存、XSS、共享设备忘记退出），对方可以改掉密码把账号彻底夺走。
    加上原密码，等于把门槛重新抬回"知道密码"，同时也能挡掉被劫持的登录态。

    和登录接口不同，这里可以明确提示"原密码错误"：请求方本来就已登录，
    这句话泄露不了新信息；登录接口不能这么提示，否则等于告诉攻击者账号是否存在。

    "两次输入不一致""新旧密码相同"已在 PasswordUpdateRequest 里拦掉了（走 422），
    这里只剩必须查库才能判断的"原密码是否正确"。
    """
    # 保存鉴权时的版本；锁定读可能刷新同一个 ORM 对象。
    expected_version = user.token_version
    try:
        user = _lock_password_user(db, user.id)
        if user.token_version != expected_version:
            raise BusinessException("登录已失效，请重新登录", 401)
        if not verify_password(data.old_password, user.password):
            raise BusinessException(message="原密码错误")

        # 密码与版本在同一事务更新；行锁避免并发改密或重置丢失递增。
        user.password = hash_password(data.new_password)
        user.token_version += 1
        db.commit()
    except Exception:
        db.rollback()
        raise


def _lock_password_user(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).populate_existing().with_for_update().first()
    if user is None:
        raise BusinessException("用户不存在", 404)
    return user


def get_user_or_404(db: Session, user_id: int) -> User:
    """按 id 取用户，取不到就报错

    每个管理接口都要先确认目标用户存在，否则下面 user.role = ... 会直接
    抛 AttributeError（None 没有这个属性），变成 500 而不是一句人话。
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise BusinessException(code=404, message="用户不存在")
    return user


def list_users_page(
    db: Session,
    page: int,
    page_size: int,
    keyword: str | None,
    role: str | None,
    status: int | None,
) -> tuple[int, list[User]]:
    """分页查询用户列表，返回 (总数, 当前页数据)"""
    query = db.query(User)

    if keyword and keyword.strip():
        # % 是 SQL LIKE 的通配符，这里不做转义：用户搜到更多结果顶多是"搜宽了"，
        # 不会造成注入（SQLAlchemy 的 like() 会把内容当参数绑定，不拼 SQL 字符串）
        pattern = f"%{keyword.strip()}%"
        query = query.filter(or_(User.username.like(pattern), User.name.like(pattern)))

    if role:
        query = query.filter(User.role == role)

    # 用 is not None 而不是 if status：status 的合法值是 0 和 1，
    # 而 0 在 Python 里是假值，写成 if status 会让"筛选已禁用用户"彻底失效
    if status is not None:
        query = query.filter(User.status == status)

    total = query.count()
    items = (
        query.order_by(User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items


def update_user_role(db: Session, current_admin: User, user_id: int, role: str) -> User:
    """修改指定用户的角色

    不允许改自己的角色：管理员一旦把自己降成学生，就没人能再进管理后台了
    （注册接口只会造学生），只能去数据库里手改。这个坑踩一次就要命的。

    注意这里只挡了"自己"，没有挡"把所有管理员都降级"——如果库里本来有多个
    管理员，互相降级仍然可能把后台锁死。真要严格，得加"至少保留一个管理员"
    的校验，这个留到后面有需要再说。
    """
    if user_id == current_admin.id:
        raise BusinessException(message="不能修改自己的角色")

    user = get_user_or_404(db, user_id)
    user.role = role
    db.commit()
    db.refresh(user)
    return user


def update_user_status(db: Session, current_admin: User, user_id: int, status: int) -> User:
    """启用 / 禁用指定用户

    同样不允许禁用自己。禁用的作用是"账号还在但登录不上"：
    login 时会检查 status，所以禁用后对方手里的 token 也会立刻失效。

    另外，禁用不会让对方的 token 从浏览器里消失，只是每次请求都会被拦回来。
    """
    if user_id == current_admin.id:
        raise BusinessException(message="不能禁用自己的账号")

    user = get_user_or_404(db, user_id)
    user.status = status
    db.commit()
    db.refresh(user)
    return user


def reset_user_password(db: Session, user_id: int, new_password: str) -> None:
    """重置指定用户的密码

    和"修改密码"接口的区别：改密码要验原密码（证明是本人），
    重置不验（管理员本来就不该知道别人的密码），所以这个接口的权限
    必须严格锁死在管理员上。

    存进库的依然是 bcrypt 密文；重置出来的密码要不要告诉用户，
    由管理员线下传达，接口不回显。
    """
    try:
        user = _lock_password_user(db, user_id)
        user.password = hash_password(new_password)
        user.token_version += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
