from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.labs import Lab
from app.models.users import User
from app.schemas.admin import (
    ResetPasswordRequest,
    UserPageResponse,
    UserRoleUpdateRequest,
    UserStatusUpdateRequest,
)
from app.schemas.lab import (
    LabCreateRequest,
    LabPageResponse,
    LabResponse,
    LabUpdateRequest,
)
from app.schemas.user import UserResponse
from app.utils.bcrypt import hash_password

router = APIRouter(prefix="/admin", tags=["管理员接口"])


def _get_user_or_404(user_id: int, db: Session) -> User:
    """按 id 取用户，取不到就报错

    每个管理接口都要先确认目标用户存在，否则下面 user.role = ... 会直接
    抛 AttributeError（None 没有这个属性），变成 500 而不是一句人话。
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise BusinessException(code=404, message="用户不存在")
    return user


@router.get("/user/list")
def list_users(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数"),
    keyword: str | None = Query(None, description="按账号或姓名模糊搜索"),
    role: str | None = Query(None, description="按角色筛选"),
    status: int | None = Query(None, description="按状态筛选：0-禁用，1-正常"),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """分页查询用户列表

    `_: User = Depends(get_current_admin)` 这个下划线参数本身用不到，
    挂在这里纯粹是为了让整个接口走一遍管理员校验——接口的准入条件写在
    函数签名里，比写在函数体内的 if 更难漏掉。
    """
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

    return Response.success(
        data=UserPageResponse(
            total=total,
            page=page,
            page_size=page_size,
            # UserResponse 里没有 password 字段，列表接口不会带出密码密文
            items=[UserResponse.model_validate(item) for item in items],
        )
    )


@router.put("/user/{user_id}/role")
def update_user_role(
    user_id: int,
    data: UserRoleUpdateRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """修改指定用户的角色

    不允许改自己的角色：管理员一旦把自己降成学生，就没人能再进管理后台了
    （注册接口只会造学生），只能去数据库里手改。这个坑踩一次就要命的。

    注意这里只挡了"自己"，没有挡"把所有管理员都降级"——如果库里本来有多个
    管理员，互相降级仍然可能把后台锁死。真要严格，得加"至少保留一个管理员"
    的校验，这个留到后面有需要再说。
    """
    if user_id == current_admin.id:
        raise BusinessException(message="不能修改自己的角色")

    user = _get_user_or_404(user_id, db)
    user.role = data.role
    db.commit()
    db.refresh(user)

    return Response.success(
        message="角色已更新", data=UserResponse.model_validate(user)
    )


@router.put("/user/{user_id}/status")
def update_user_status(
    user_id: int,
    data: UserStatusUpdateRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """启用 / 禁用指定用户

    同样不允许禁用自己。禁用的作用是"账号还在但登录不上"：
    get_current_user 里会检查 status，所以禁用后对方手里的 token 也会立刻失效。

    另外，禁用不会让对方的 token 从浏览器里消失，只是每次请求都会被 401 挡回来。
    """
    if user_id == current_admin.id:
        raise BusinessException(message="不能禁用自己的账号")

    user = _get_user_or_404(user_id, db)
    user.status = data.status
    db.commit()
    db.refresh(user)

    action = "已启用" if data.status == 1 else "已禁用"
    return Response.success(message=f"账号{action}", data=UserResponse.model_validate(user))


@router.put("/user/{user_id}/password")
def reset_user_password(
    user_id: int,
    data: ResetPasswordRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """重置指定用户的密码

    和"修改密码"接口的区别：改密码要验原密码（证明是本人），
    重置不验（管理员本来就不该知道别人的密码），所以这个接口的权限
    必须严格锁死在管理员上。

    存进库的依然是 bcrypt 密文；重置出来的密码要不要告诉用户，
    由管理员线下传达，接口不回显。
    """
    user = _get_user_or_404(user_id, db)
    user.password = hash_password(data.new_password)
    db.commit()

    return Response.success(message="密码已重置")


# ============ 实验室管理 ============


def _get_lab_or_404(lab_id: int, db: Session) -> Lab:
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    if not lab:
        raise BusinessException(code=404, message="实验室不存在")
    return lab


def _ensure_code_available(
    code: str, db: Session, exclude_lab_id: int | None = None
) -> None:
    """房间号查重

    exclude_lab_id 用在修改的场景：一间实验室改其它字段时，
    它自己的房间号当然算"被占用"，所以要把它自己排除掉。
    """
    query = db.query(Lab).filter(Lab.code == code)
    if exclude_lab_id is not None:
        query = query.filter(Lab.id != exclude_lab_id)
    if query.first():
        raise BusinessException(code=409, message=f"房间号 {code} 已被其它实验室占用")


@router.get("/lab/list")
def admin_list_labs(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数"),
    keyword: str | None = Query(None, description="按名称、房间号或楼栋模糊搜索"),
    category: str | None = Query(None, description="按类别筛选"),
    status: str | None = Query(None, description="按状态筛选"),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """分页查询实验室（管理端）"""
    query = db.query(Lab)

    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Lab.name.like(pattern),
                Lab.code.like(pattern),
                Lab.building.like(pattern),
            )
        )

    if category:
        query = query.filter(Lab.category == category)

    if status:
        query = query.filter(Lab.status == status)

    total = query.count()
    items = (
        query.order_by(Lab.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return Response.success(
        data=LabPageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[LabResponse.model_validate(item) for item in items],
        )
    )


@router.post("/lab")
def create_lab(
    data: LabCreateRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """新增实验室"""
    _ensure_code_available(data.code, db)

    lab = Lab(**data.model_dump())
    try:
        db.add(lab)
        db.commit()
        db.refresh(lab)
    except IntegrityError as exc:
        # 兜底：上面查重和这里插入之间有时间差，并发时两个请求可能都查到
        # "不存在"，最终由数据库的唯一索引拦下第二个。
        # 这里必须 rollback，否则 session 会卡在"事务失败"状态，后续操作全报错。
        db.rollback()
        raise BusinessException(
            code=409, message=f"房间号 {data.code} 已被其它实验室占用"
        ) from exc

    return Response.success(
        message="实验室已创建", data=LabResponse.model_validate(lab)
    )


@router.put("/lab/{lab_id}")
def update_lab(
    lab_id: int,
    data: LabUpdateRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """修改实验室（全量更新）"""
    lab = _get_lab_or_404(lab_id, db)
    _ensure_code_available(data.code, db, exclude_lab_id=lab_id)

    for field, value in data.model_dump().items():
        setattr(lab, field, value)

    try:
        db.commit()
        db.refresh(lab)
    except IntegrityError as exc:
        db.rollback()
        raise BusinessException(
            code=409, message=f"房间号 {data.code} 已被其它实验室占用"
        ) from exc

    return Response.success(
        message="实验室已更新", data=LabResponse.model_validate(lab)
    )


@router.delete("/lab/{lab_id}")
def delete_lab(
    lab_id: int,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """删除实验室

    会连带删掉这间实验室下的所有设备（模型里配了 cascade）。
    之所以敢直接级联，是因为设备本来就依附于实验室、脱离实验室没有意义。
    等预约表建起来之后，这里要改成"有预约记录就不允许删"，否则会删掉
    学生预约所指向的实验室——那属于数据丢失，不是数据清理。
    """
    lab = _get_lab_or_404(lab_id, db)

    equipment_count = len(lab.equipments)
    db.delete(lab)
    db.commit()

    message = "实验室已删除"
    if equipment_count:
        message = f"实验室及其 {equipment_count} 台设备已删除"

    return Response.success(message=message)
