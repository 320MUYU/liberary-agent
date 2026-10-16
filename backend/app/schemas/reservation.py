from datetime import date, datetime, timedelta, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TIME_PATTERN = r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"


def reservation_time(value):
    """Old MySQL TIME columns use timedelta; current schemas store HH:MM strings."""
    if isinstance(value, timedelta):
        seconds = value.total_seconds()
        if not 0 <= seconds < 86400:
            raise ValueError("预约时间必须在同一天内")
        value = (datetime.min + value).time()
    if isinstance(value, time):
        return value.isoformat(timespec="minutes" if not value.second and not value.microsecond else "seconds")
    return value


class ReservationCreateRequest(BaseModel):
    lab_id: int = Field(ge=1)
    date: date
    start: str = Field(pattern=TIME_PATTERN)
    end: str = Field(pattern=TIME_PATTERN)
    people: int = Field(ge=1, le=1000)
    purpose: str = Field(min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=200)

    @field_validator("purpose")
    @classmethod
    def purpose_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请填写使用用途")
        return value

    @model_validator(mode="after")
    def valid_interval(self):
        if self.start >= self.end:
            raise ValueError("结束时间需要晚于开始时间")
        return self


class ReservationReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    review_note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def rejected_reason_required(self):
        if self.status == "rejected" and not (self.review_note and self.review_note.strip()):
            raise ValueError("驳回预约时必须填写理由")
        if self.review_note:
            self.review_note = self.review_note.strip()
        return self


class ReservationResponse(BaseModel):
    id: int
    lab_id: int
    lab_name: str
    lab_code: str
    applicant_id: int
    applicant_name: str
    date: date
    start: str
    end: str
    people: int
    purpose: str
    note: str | None
    status: str
    created_at: datetime
    review_note: str | None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("start", "end", mode="before")
    @classmethod
    def legacy_time(cls, value):
        return reservation_time(value)


class ReservationPageResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ReservationResponse]


def reservation_response(reservation) -> ReservationResponse:
    return ReservationResponse(
        id=reservation.id,
        lab_id=reservation.lab_id,
        lab_name=reservation.lab.name,
        lab_code=reservation.lab.code,
        applicant_id=reservation.applicant_id,
        applicant_name=reservation.applicant.name,
        date=reservation.date,
        start=reservation.start,
        end=reservation.end,
        people=reservation.people,
        purpose=reservation.purpose,
        note=reservation.note,
        status=reservation.status,
        created_at=reservation.create_time,
        review_note=reservation.review_note,
    )
