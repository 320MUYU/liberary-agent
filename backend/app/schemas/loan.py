from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


LoanStatus = Literal["pending", "borrowed", "return_pending", "returned", "rejected", "cancelled"]


class LoanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    book_id: int = Field(gt=0, strict=True)


class BorrowConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    copy_id: int | None = Field(default=None, gt=0, strict=True)


class LoanRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class LoanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    book_id: int
    book_title: str
    reader_id: int
    reader_name: str
    reader_username: str
    status: LoanStatus
    copy_id: int | None = None
    barcode: str | None = None
    location: str | None = None
    borrowed_at: datetime | None = None
    due_at: datetime | None = None
    return_requested_at: datetime | None = None
    returned_at: datetime | None = None
    reject_reason: str | None = None
    create_time: datetime
    is_overdue: bool = False


class LoanPageResponse(BaseModel):
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
    items: list[LoanResponse] = Field(default_factory=list)
