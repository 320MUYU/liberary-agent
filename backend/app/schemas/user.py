from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserResponse(BaseModel):
    id: int
    username: str
    name: str
    role: str
    email: str | None = None
    phone: str | None = None
    avatar: str | None = None
    status: int

    model_config = ConfigDict(from_attributes=True)


class UserUpdateRequest(BaseModel):
    """修改个人信息请求参数

    只开放「姓名、邮箱、手机号、头像」四个可改项：
    - username 是登录账号，改它会导致登录态和关联数据错乱，这里不接受
    - role / status 属于权限与账号状态，只能由管理员操作，同样不开放
    - avatar 存的是上传接口返回的 url（形如 /uploads/xxx.jpg），不是文件本身
    """

    name: str = Field(min_length=1, max_length=50, description="姓名")
    email: str | None = Field(default=None, max_length=50, description="邮箱")
    phone: str | None = Field(default=None, max_length=50, description="手机号")
    avatar: str | None = Field(default=None, max_length=50, description="头像 url")


class PasswordUpdateRequest(BaseModel):
    """修改密码的请求参数

    长度限制（6-32 位）与注册时保持一致，否则会出现"注册不让设的密码，
    改密码反而能设"的漏洞。
    confirm_password 和注册一样只在这一次校验里用，不落库。
    """

    old_password: str = Field(min_length=6, max_length=32, description="原密码")
    new_password: str = Field(
        min_length=6, max_length=32, description="新密码：6-32 位"
    )
    confirm_password: str = Field(description="确认新密码：仅用于校验，不落库")

    @model_validator(mode="after")
    def validate_password(self):
        """跨字段校验：这两条都只看请求参数本身，不碰数据库

        - "两次输入不一致"是手滑，属于参数错误
        - "新旧密码相同"这里先拦一道，省掉一次没意义的 bcrypt 计算；
          真正的"原密码对不对"要查库比对密文，只能放在接口里做
        """
        if self.new_password != self.confirm_password:
            raise ValueError("两次输入的新密码不一致")
        if self.new_password == self.old_password:
            raise ValueError("新密码不能跟原密码相同")
        return self

