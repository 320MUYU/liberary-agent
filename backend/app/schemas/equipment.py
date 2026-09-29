from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EquipmentResponse(BaseModel):
    id: int
    name: str
    model: str | None = None
    total: int
    available: int
    status: str
    lab_id: int

    model_config = ConfigDict(from_attributes=True)


class EquipmentCreateRequest(BaseModel):
    """新增设备"""

    name: str = Field(min_length=1, max_length=50, description="设备名称")
    model: str | None = Field(default=None, max_length=50, description="型号")
    total: int = Field(default=1, ge=1, le=9999, description="总数量")
    available: int = Field(default=1, ge=0, le=9999, description="可用数量")
    status: Literal["normal", "repair", "scrapped"] = Field(
        default="normal", description="状态：normal-正常，repair-维修中，scrapped-已报废"
    )
    lab_id: int = Field(description="所属实验室 id")

    @model_validator(mode="after")
    def validate_available(self):
        """可用数量不能大于总数量

        "3 台设备里有 5 台可用"是自相矛盾的，与其让这种数据进库，
        不如在这里直接拦掉（走 422 参数错误）。
        """
        if self.available > self.total:
            raise ValueError("可用数量不能大于总数量")
        return self


class EquipmentUpdateRequest(EquipmentCreateRequest):
    """修改设备：字段与新增一致，PUT 全量更新"""
