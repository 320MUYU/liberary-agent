import re

from pydantic import BaseModel, Field, field_validator, model_validator

# 账号白名单：只允许字母、数字、下划线，避免出现空格/中文/特殊符号带来的后续麻烦
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,20}$")


class LoginRequest(BaseModel):
    """登录请求参数"""

    username: str
    password: str


class RegisterRequest(BaseModel):
    """注册请求参数

    这里只声明"注册时前端要传什么"，和数据库表结构（User 模型）是两回事：
    - confirm_password 只在注册这一刻用于校验，永远不会写进数据库，所以它只存在于 Schema 里
    - role / status 等字段由后端自己决定，不允许前端传，防止有人自己注册成管理员
    """

    username: str = Field(
        min_length=3, max_length=20, description="账号：3-20 位字母、数字、下划线"
    )
    password: str = Field(min_length=6, max_length=32, description="密码：6-32 位")
    confirm_password: str = Field(description="确认密码：仅用于校验，不落库")
    name: str = Field(min_length=1, max_length=50, description="姓名")

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """单字段校验：Field 的 min_length/max_length 只管长度，格式要靠自己写

        校验不通过就 raise ValueError，FastAPI 会自动把它转成 422 参数错误。
        """
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError("账号只能包含字母、数字、下划线，长度 3-20 位")
        return value

    @model_validator(mode="after")
    def validate_password_match(self):
        """跨字段校验：要比较两个字段，单字段的 field_validator 做不到

        mode="after" 表示"等所有字段各自的校验都通过之后，再执行这里"。
        注意这里能直接读到 self.username / self.password，因为它们已经校验完了。
        """
        if self.password != self.confirm_password:
            raise ValueError("两次输入的密码不一致")
        return self
