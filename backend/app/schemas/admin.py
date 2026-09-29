from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.user import UserResponse


class UserPageResponse(BaseModel):
    """用户列表的分页返回体

    列表接口一定要分页：用户涨起来之后一次性全查出来，既拖慢接口又吃内存，
    而且前端表格一次渲染几千行也会卡。
    """

    total: int
    page: int
    page_size: int
    items: list[UserResponse]


class UserRoleUpdateRequest(BaseModel):
    """修改用户角色

    用 Literal 而不是 str：角色只有这两种取值，写死在这里，
    接口就不会被塞进 "superadmin" 这种数据库里根本没有的角色。
    """

    role: Literal["student", "admin"] = Field(
        description="角色：student-学生，admin-管理员"
    )


class UserStatusUpdateRequest(BaseModel):
    """启用 / 禁用用户"""

    status: Literal[0, 1] = Field(description="状态：0-禁用，1-正常")


class ResetPasswordRequest(BaseModel):
    """管理员重置他人密码

    长度规则和注册、改密码保持一致（6-32 位）。
    """

    new_password: str = Field(min_length=6, max_length=32, description="新密码：6-32 位")
