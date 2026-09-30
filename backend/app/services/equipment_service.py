"""设备业务逻辑：管理端增删改查

设备挂在实验室下，所以新增/修改前要先确认实验室存在——
这一步复用 lab_service.get_lab_or_404，不在本模块重复实现。
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.models.equipments import Equipment
from app.schemas.equipment import EquipmentCreateRequest, EquipmentUpdateRequest
from app.services import lab_service


def get_equipment_or_404(db: Session, equipment_id: int) -> Equipment:
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise BusinessException(code=404, message="设备不存在")
    return equipment


def list_equipments_page(
    db: Session,
    page: int,
    page_size: int,
    lab_id: int | None,
    keyword: str | None,
    status: str | None,
) -> tuple[int, list[Equipment]]:
    """分页查询设备（管理端），返回 (总数, 当前页数据)

    lab_id 可选：传了就只查这间实验室的设备（管理页面用它做联动筛选），
    不传就是全平台的设备。
    """
    query = db.query(Equipment)

    # 用 is not None 而不是 if lab_id：lab_id 为 0 虽然不该出现，
    # 但和 status 一样，这类"合法值可能是假值"的字段一律显式判断
    if lab_id is not None:
        query = query.filter(Equipment.lab_id == lab_id)

    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        # model 可能为空，SQL 里 NULL LIKE '%x%' 的结果是 NULL（不是真），
        # 所以型号为空的设备在按型号搜索时不会命中，这是符合预期的
        query = query.filter(
            or_(Equipment.name.like(pattern), Equipment.model.like(pattern))
        )

    if status:
        query = query.filter(Equipment.status == status)

    total = query.count()
    items = (
        query.order_by(Equipment.lab_id, Equipment.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items


def create_equipment(db: Session, data: EquipmentCreateRequest) -> Equipment:
    """新增设备"""
    lab_service.get_lab_or_404(db, data.lab_id)

    equipment = Equipment(**data.model_dump())
    db.add(equipment)
    db.commit()
    db.refresh(equipment)
    return equipment


def update_equipment(
    db: Session, equipment_id: int, data: EquipmentUpdateRequest
) -> Equipment:
    """修改设备（全量更新）

    lab_id 也是全量更新的一部分，所以设备可以被改挂到另一间实验室。
    """
    equipment = get_equipment_or_404(db, equipment_id)
    lab_service.get_lab_or_404(db, data.lab_id)

    for field, value in data.model_dump().items():
        setattr(equipment, field, value)

    db.commit()
    db.refresh(equipment)
    return equipment


def delete_equipment(db: Session, equipment_id: int) -> None:
    """删除设备；预约当前只关联实验室，不单独关联设备。"""
    equipment = get_equipment_or_404(db, equipment_id)
    db.delete(equipment)
    db.commit()
