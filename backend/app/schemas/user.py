from pydantic import BaseModel, ConfigDict, Field


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
