import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


CopyStatus = Literal["available", "maintenance", "withdrawn"]


class BookCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=255, description="书名")
    author: str = Field(min_length=1, max_length=255, description="作者")
    isbn: str | None = Field(default=None, max_length=13, description="ISBN-10 或 ISBN-13")
    publisher: str | None = Field(default=None, max_length=255, description="出版社")
    publication_year: int | None = Field(
        default=None, ge=1, le=9999, strict=True, description="出版年份"
    )
    category: str = Field(default="未分类", min_length=1, max_length=100, description="分类")
    description: str | None = Field(default=None, max_length=5000, description="图书简介")
    cover: str | None = Field(default=None, max_length=255, description="封面地址")
    is_active: StrictBool = Field(default=True, description="是否上架")

    @field_validator("title", "author", "category", mode="before")
    @classmethod
    def trim_required_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("publisher", "description", "cover", mode="before")
    @classmethod
    def trim_optional_text(cls, value):
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("isbn", mode="before")
    @classmethod
    def normalize_isbn(cls, value):
        if not isinstance(value, str):
            return value
        if not value.strip():
            return None

        # 分隔符不参与 ISBN 存储与唯一性判断；ISBN-10 的校验字符统一为大写 X。
        isbn = re.sub(r"[\s-]", "", value).upper()
        if re.fullmatch(r"[0-9]{9}[0-9X]", isbn):
            digits = [int(char) if char != "X" else 10 for char in isbn]
            if sum((10 - index) * digit for index, digit in enumerate(digits)) % 11 == 0:
                return isbn
        elif re.fullmatch(r"97[89][0-9]{10}", isbn):
            checksum = sum(
                int(char) * (1 if index % 2 == 0 else 3)
                for index, char in enumerate(isbn)
            )
            if checksum % 10 == 0:
                return isbn

        raise ValueError("请输入有效的 ISBN-10 或 ISBN-13")


class BookUpdateRequest(BookCreateRequest):
    """全量更新书目信息，与现有项目的 PUT 表单约定一致。"""


class BookCopyUpdateRequest(BaseModel):
    """仅维护副本信息，不接受所属书目或库存数量。"""

    model_config = ConfigDict(extra="forbid")

    barcode: str = Field(min_length=1, max_length=50, description="馆藏唯一条码")
    location: str = Field(min_length=1, max_length=100, description="馆藏位置")
    status: CopyStatus = Field(default="available", description="馆藏副本状态")

    @field_validator("barcode", "location", mode="before")
    @classmethod
    def trim_required_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class BookCopyCreateRequest(BookCopyUpdateRequest):
    book_id: int = Field(ge=1, strict=True, description="所属书目 ID")


class BookSourceResponse(BaseModel):
    name: str = "Open Library"
    url: str
    languages: list[str] = Field(default_factory=list)


class BookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    author: str
    isbn: str | None = None
    publisher: str | None = None
    publication_year: int | None = None
    category: str
    description: str | None = None
    cover: str | None = None
    is_active: bool
    source: BookSourceResponse | None = None
    # 由后续查询服务聚合副本后填充，ORM 模型不保存库存数量。
    total_copies: int = Field(default=0, ge=0)
    available_copies: int = Field(default=0, ge=0)


class BookCopyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    book_id: int
    barcode: str
    location: str
    status: CopyStatus
    is_on_loan: bool = False


class BookPageResponse(BaseModel):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    items: list[BookResponse] = Field(default_factory=list)


class BookCopyPageResponse(BaseModel):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    items: list[BookCopyResponse] = Field(default_factory=list)
