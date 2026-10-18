"""Read-only room metadata and requested-slot availability; never reveals bookings."""

from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import or_

from app.common.exceptions import BusinessException
from app.models.equipments import Equipment
from app.models.labs import Lab
from app.models.reservations import Reservation
from app.schemas.reservation import TIME_PATTERN


class SpaceInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date: date
    start: str = Field(pattern=TIME_PATTERN)
    end: str = Field(pattern=TIME_PATTERN)

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


class SpaceConditions(SpaceInterval):
    people: int = Field(ge=1, le=1000, strict=True)
    purpose: str = Field(min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=200)


class SpaceAvailabilityConditions(SpaceInterval):
    people: int | None = Field(default=None, ge=1, le=1000, strict=True)


def room_snapshot(lab):
    return {field: getattr(lab, field) for field in
        ("id", "name", "code", "building", "floor", "capacity", "category", "status")}


def _result(db, conditions, rooms, total, page, keyword, checked_at=None):
    now = checked_at if checked_at is not None else datetime.now()
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
        if conditions.people is not None and room.capacity < conditions.people:
            reasons.append("capacity")
        if room.id in occupied:
            reasons.append("approved_conflict")
        if starts_at < now.replace(tzinfo=None) + timedelta(hours=2):
            reasons.append("too_late")
        spaces.append({**room_snapshot(room), "description": room.description,
            "equipments": [{"name": equipment.name, "available": equipment.available,
                "status": equipment.status} for equipment in room.equipments],
            "can_reserve": not reasons, "unavailable_reasons": reasons})
    return {"spaces": spaces, "conditions": conditions.model_dump(mode="json"),
        "total": total, "page": page, "page_size": 6, "keyword": keyword,
        "checked_at": now.isoformat(), "message": "指定时段检查结果；提交时再次校验，申请仍需管理员审核。"}


def _matching_spaces(db, keyword):
    query = db.query(Lab)
    if keyword.strip():
        pattern = "%" + keyword.strip() + "%"
        query = query.filter(or_(Lab.name.like(pattern), Lab.code.like(pattern),
            Lab.building.like(pattern), Lab.category.like(pattern),
            Lab.equipments.any(Equipment.name.like(pattern))))
    return query


def discover_spaces(db, conditions, keyword="", page=1, *, checked_at=None):
    query = _matching_spaces(db, keyword)
    total = query.count()
    rooms = query.populate_existing().order_by(Lab.code, Lab.id).offset((page - 1) * 6).limit(6).all()
    return _result(db, conditions, rooms, total, page, keyword, checked_at)


def search_space_catalogue(db, keyword="", page=1, *, checked_at=None):
    query = _matching_spaces(db, keyword)
    total = query.count()
    rooms = query.populate_existing().order_by(Lab.code, Lab.id).offset((page - 1) * 6).limit(6).all()
    return {"spaces": [{**room_snapshot(room), "description": room.description,
        "equipments": [{"name": item.name, "available": item.available, "status": item.status}
            for item in room.equipments]} for room in rooms],
        "total": total, "page": page, "page_size": 6, "keyword": keyword,
        "checked_at": checked_at.isoformat() if checked_at is not None else datetime.now().isoformat(),
        "opening_calendar": "not_configured",
        "message": "仅为系统登记的空间信息，不表示某日开放或时段空闲。尚未配置正式开放日历。"}


def get_space(db, conditions, space_id):
    room = db.query(Lab).filter_by(id=space_id).populate_existing().first()
    if room is None:
        raise BusinessException("学习空间不存在", 404)
    return _result(db, conditions, [room], 1, 1, "")
