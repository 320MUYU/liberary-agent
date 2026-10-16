"""Read-only room metadata and requested-slot availability; never reveals bookings."""

from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import or_

from app.common.exceptions import BusinessException
from app.models.equipments import Equipment
from app.models.labs import Lab
from app.models.reservations import Reservation
from app.schemas.reservation import TIME_PATTERN


class SpaceConditions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date: date
    start: str = Field(pattern=TIME_PATTERN)
    end: str = Field(pattern=TIME_PATTERN)
    people: int = Field(ge=1, le=1000, strict=True)
    purpose: str = Field(min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=200)

    @field_validator("date", mode="before")
    @classmethod
    def explicit_date(cls, value):
        if not isinstance(value, (str, date)) or isinstance(value, datetime):
            raise ValueError("请选择明确日期")
        return value

    @model_validator(mode="after")
    def interval(self):
        if self.start >= self.end:
            raise ValueError("结束时间需要晚于开始时间")
        return self


def room_snapshot(lab):
    return {field: getattr(lab, field) for field in
        ("id", "name", "code", "building", "floor", "capacity", "category", "status")}


def _result(db, conditions, rooms, total, page, keyword):
    now = datetime.now()
    ids = [room.id for room in rooms]
    occupied = set(row[0] for row in db.query(Reservation.lab_id).filter(
        Reservation.lab_id.in_(ids), Reservation.date == conditions.date,
        Reservation.status == "approved", Reservation.start < conditions.end,
        Reservation.end > conditions.start).distinct().all()) if ids else set()
    starts_at = datetime.combine(conditions.date, datetime.strptime(conditions.start, "%H:%M").time())
    spaces = []
    for room in rooms:
        reasons = []
        if room.status == "maintenance":
            reasons.append("maintenance")
        if room.capacity < conditions.people:
            reasons.append("capacity")
        if room.id in occupied:
            reasons.append("approved_conflict")
        if starts_at < now + timedelta(hours=2):
            reasons.append("too_late")
        spaces.append({**room_snapshot(room), "description": room.description,
            "equipments": [{"name": equipment.name, "available": equipment.available,
                "status": equipment.status} for equipment in room.equipments],
            "can_reserve": not reasons, "unavailable_reasons": reasons})
    return {"spaces": spaces, "conditions": conditions.model_dump(mode="json"),
        "total": total, "page": page, "page_size": 6, "keyword": keyword,
        "checked_at": now.isoformat(), "message": "指定时段检查结果；提交时再次校验，申请仍需管理员审核。"}


def discover_spaces(db, conditions, keyword="", page=1):
    query = db.query(Lab)
    if keyword.strip():
        pattern = "%" + keyword.strip() + "%"
        query = query.filter(or_(Lab.name.like(pattern), Lab.code.like(pattern),
            Lab.building.like(pattern), Lab.category.like(pattern),
            Lab.equipments.any(Equipment.name.like(pattern))))
    total = query.count()
    rooms = query.populate_existing().order_by(Lab.code, Lab.id).offset((page - 1) * 6).limit(6).all()
    return _result(db, conditions, rooms, total, page, keyword)


def get_space(db, conditions, space_id):
    room = db.query(Lab).filter_by(id=space_id).populate_existing().first()
    if room is None:
        raise BusinessException("学习空间不存在", 404)
    return _result(db, conditions, [room], 1, 1, "")
