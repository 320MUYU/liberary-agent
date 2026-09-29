from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.equipment import EquipmentResponse


class LabResponse(BaseModel):
    id: int
    name: str
    code: str
    building: str
    floor: str
    capacity: int
    category: str
    status: str
    description: str | None = None
    cover: str | None = None
    # 实验室详情里直接带上设备列表，学生端不用再单独发一次请求
    equipments: list[EquipmentResponse] = []

    model_config = ConfigDict(from_attributes=True)


class LabCreateRequest(BaseModel):
    """新增实验室

    注意这里没有"利用率""最近空闲"这类字段：那些是从预约记录算出来的结果，
    不是实验室本身的属性。等预约表建起来之后由后端算，不该让管理员手填一个
    跟真实情况无关的数字。
    """

    name: str = Field(min_length=1, max_length=50, description="实验室名称")
    code: str = Field(min_length=1, max_length=20, description="房间号，如 A-301")
    building: str = Field(min_length=1, max_length=50, description="所属楼栋")
    floor: str = Field(min_length=1, max_length=10, description="楼层")
    capacity: int = Field(ge=1, le=1000, description="可容纳人数")
    category: str = Field(min_length=1, max_length=50, description="类别")
    status: Literal["available", "busy", "maintenance"] = Field(
        default="available", description="状态：available-可预约，busy-使用中，maintenance-维护中"
    )
    description: str | None = Field(default=None, max_length=255, description="简介")
    cover: str | None = Field(default=None, max_length=255, description="封面图 url")


class LabUpdateRequest(LabCreateRequest):
    """修改实验室

    字段和新增完全一样：编辑弹窗本来就是整份表单提交回前端，
    所以走全量更新（PUT），不做"只改传过来的字段"那种局部更新——
    局部更新会让"想把简介清空"这种操作没法表达（不传 = 不改）。
    """


class LabPageResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[LabResponse]
