"""实验室业务逻辑：学生端查询 + 管理端增删改查

分层约定同上：只收 db 会话与入参，返回 ORM 对象或简单值。
"""

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.models.labs import Lab
from app.models.reservations import Reservation
from app.schemas.lab import LabCreateRequest, LabUpdateRequest


def list_labs(db: Session) -> list[Lab]:
    """实验室列表

    这里故意不分页：实验室是数量有限的几十间，而且学生端本来就要
    一次拿到全部再在浏览器里按类别/状态筛选（和"用户列表"那种会持续增长的
    数据是两回事）。真到了几百间再改成按需查询也不迟。
    """
    # Lab 上的 equipments 用了 lazy="selectin"，所以这里一次查询就能
    # 把每间实验室的设备一起带出来，不会出现 N+1
    return db.query(Lab).order_by(Lab.code).all()


def get_lab_or_404(db: Session, lab_id: int, *, for_update=False) -> Lab:
    """按 id 取实验室，取不到就报错

    新增/修改设备时也用它校验 lab_id：外键约束虽然也会拦下不存在的 lab_id，
    但那抛出来的是 IntegrityError（500），这里能给出一句人话（404）。
    """
    query = db.query(Lab).filter(Lab.id == lab_id).populate_existing()
    lab = (query.with_for_update() if for_update else query).first()
    if not lab:
        raise BusinessException(code=404, message="学习空间不存在")
    return lab


def ensure_code_available(
    db: Session, code: str, exclude_lab_id: int | None = None
) -> None:
    """房间号查重

    exclude_lab_id 用在修改的场景：一间实验室改其它字段时，
    它自己的房间号当然算"被占用"，所以要把它自己排除掉。
    """
    query = db.query(Lab).filter(Lab.code == code)
    if exclude_lab_id is not None:
        query = query.filter(Lab.id != exclude_lab_id)
    if query.first():
        raise BusinessException(code=409, message=f"房间号 {code} 已被其它学习空间占用")


def list_labs_page(
    db: Session,
    page: int,
    page_size: int,
    keyword: str | None,
    category: str | None,
    status: str | None,
) -> tuple[int, list[Lab]]:
    """分页查询实验室（管理端），返回 (总数, 当前页数据)"""
    query = db.query(Lab)

    if keyword and keyword.strip():
        pattern = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Lab.name.like(pattern),
                Lab.code.like(pattern),
                Lab.building.like(pattern),
            )
        )

    if category:
        query = query.filter(Lab.category == category)

    if status:
        query = query.filter(Lab.status == status)

    total = query.count()
    items = (
        query.order_by(Lab.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return total, items


def create_lab(db: Session, data: LabCreateRequest) -> Lab:
    """新增实验室"""
    ensure_code_available(db, data.code)

    lab = Lab(**data.model_dump())
    try:
        db.add(lab)
        db.commit()
        db.refresh(lab)
    except IntegrityError as exc:
        # 兜底：上面查重和这里插入之间有时间差，并发时两个请求可能都查到
        # "不存在"，最终由数据库的唯一索引拦下第二个。
        # 这里必须 rollback，否则 session 会卡在"事务失败"状态，后续操作全报错。
        db.rollback()
        raise BusinessException(
            code=409, message=f"房间号 {data.code} 已被其它学习空间占用"
        ) from exc

    return lab


def update_lab(db: Session, lab_id: int, data: LabUpdateRequest) -> Lab:
    """修改实验室（全量更新）"""
    lab = get_lab_or_404(db, lab_id, for_update=True)
    ensure_code_available(db, data.code, exclude_lab_id=lab_id)

    for field, value in data.model_dump().items():
        setattr(lab, field, value)

    try:
        db.commit()
        db.refresh(lab)
    except IntegrityError as exc:
        db.rollback()
        raise BusinessException(
            code=409, message=f"房间号 {data.code} 已被其它学习空间占用"
        ) from exc

    return lab


def delete_lab(db: Session, lab_id: int) -> int:
    """删除实验室及其设备，返回被一并删掉的设备**种类数**

    有预约记录时不允许删：预约表存的是 lab_id，实验室没了这些记录就指向空气。
    返回值只统计设备记录的条数（"种"），不是把 total 加起来得到的台数——
    具体文案由 api 层拼。
    """
    lab = get_lab_or_404(db, lab_id, for_update=True)
    if db.query(Reservation.id).filter(Reservation.lab_id == lab_id).first():
        raise BusinessException(code=409, message="学习空间已有预约记录，不能删除")

    equipment_count = len(lab.equipments)
    db.delete(lab)
    db.commit()
    return equipment_count
