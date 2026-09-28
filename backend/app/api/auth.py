from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.schemas.auth import LoginRequest, RegisterRequest
from app.database import get_db
from app.models.users import User
from app.schemas.user import UserResponse
from app.utils.bcrypt import hash_password, verify_password
from app.utils.jwt import create_access_token
from app.common.response import Response
from app.common.exceptions import BusinessException

router = APIRouter(prefix="/auth", tags=["权限验证接口"])


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    # 根据用户账号查询数据库
    user = db.query(User).filter(User.username == data.username).first()

    # 判断账号和密码是否正确
    # 注意这里不分"账号不存在"和"密码错误"两种情况分别提示：
    # 分开提示等于告诉攻击者"这个账号存在"，可以拿来枚举平台上有哪些用户
    if not user or not verify_password(data.password, user.password):
        raise BusinessException(code=401, message="账号或密码错误")

    # 验证账号的状态
    if user.status != 1:
        raise BusinessException(code=403, message="账号被禁用")

    # 创建token
    token = create_access_token(user.id)

    # 返回信息
    return Response.success(
        data={"token": token, "user": UserResponse.model_validate(user)}
    )


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册

    流程：查重 -> 组装 User 对象 -> 落库 -> 返回新用户信息
    注册成功后不签发 token，前端引导用户去登录页手动登录。
    """
    # 第1步：查重
    # 早查一次的好处是能给用户友好提示；坏处是"查"和"插"之间有时间差，
    # 并发时可能两个请求都查到"不存在"，所以下面还要靠唯一索引兜底（见第3步）
    existing_user = db.query(User).filter(User.username == data.username).first()
    if existing_user:
        raise BusinessException(code=409, message="该账号已被注册，请更换后重试")

    # 第2步：组装 User 对象
    # 关键点1：存进数据库的是 hash_password 之后的密文，明文密码绝不落库。
    #   bcrypt 每次生成的盐都不同，所以同一个密码两次注册得到的密文也不一样。
    # 关键点2：role 和 status 写死在这里，不接受前端传参。
    #   如果把 role 开放给请求参数，别人注册时传 "admin" 就能直接拿到管理员权限。
    user = User(
        username=data.username,
        password=hash_password(data.password),
        name=data.name,
        role="student",
        status=1,
    )

    # 第3步：写库
    try:
        db.add(user)      # 把对象放进 session 的"待提交"队列
        db.commit()       # 真正执行 INSERT，事务提交
        db.refresh(user)  # 回读一次，拿到数据库生成的主键 id 和默认时间
    except IntegrityError as exc:
        # 并发兜底：上面的查重和这里的插入之间存在时间差，
        # 同一账号的第二个请求会撞上 username 的唯一索引，在这里被拦下。
        # 必须 rollback，否则这个 session 会一直处于"事务已失败"状态，后续操作全部报错。
        db.rollback()
        raise BusinessException(
            code=409, message="该账号已被注册，请更换后重试"
        ) from exc

    # 第4步：返回新用户信息（UserResponse 里没有 password 字段，不会泄露密文）
    return Response.success(
        message="注册成功，请登录", data=UserResponse.model_validate(user)
    )
