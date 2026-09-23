#通过jwt生成并解析token
import jwt                                          # PyJWT：负责签发(encode)和校验(decode) token
from datetime import datetime, timedelta, timezone  # datetime=取当前时间  timedelta=算时间偏移  timezone=时区
from app.config import settings                     # 小写 settings 是配置实例，JWT_SECRET_KEY 这些值都挂在它身上


def create_access_token(user_id: int) -> str:
    """签发 token：把用户 id 签成一张"通行证"，返回字符串"""
    # 第1步：算过期时间 = 当前 UTC 时间 + 配置里的小时数（.env 中 JWT_EXPIRE_HOURS=24）
    #   必须用 timezone.utc：datetime.now() 是本地时间，而 PyJWT 会把"不带时区的值"当成 UTC，
    #   在中国(UTC+8)会让有效期凭空多出 8 小时
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRE_HOURS)

    # 第2步：组装 payload（载荷）—— 想装进 token 的信息，就是一个字典
    payload = {
        "user_id": user_id,  # 自定义字段：将来凭它反查"这个人是谁"
        "exp": expire,       # 注册声明（固定名字）：过期时间。必须叫 exp，PyJWT 才会自动把它转成时间戳、并在校验时检查是否过期
    }

    # 第3步：用密钥给 payload 签名，生成"三段式"的 token 字符串
    #   结构：header(算法信息) . payload(上面的内容，任何人都能读出来) . signature(签名，改了就失效)
    #   JWT_SECRET_KEY 只有后端知道，这是"别人无法伪造 token"的根本保证
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    # 第4步：把 token 交给调用方（登录接口会把它放进响应，返回给前端保存）
    return token


def decode_access_token(token: str) -> int:
    """校验 token：验签 + 检查是否过期；通过就返回里面的 payload"""
    # 用同一把密钥验签，以下三种情况都会在这里抛异常：
    #   1) 内容被改过（签名对不上）  2) 不是这把密钥签的  3) 已经过期(ExpiredSignatureError)
    # 注意：参数名是 algorithms（复数）且要传列表，别和上面 encode 的 algorithm（单数、字符串）搞混
    # 返回的其实是字典，例如 user_id 与 exp 两个键，所以这里标注 -> int 并不准确
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=settings.JWT_ALGORITHM)


