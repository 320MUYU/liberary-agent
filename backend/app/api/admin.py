from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.users import User
from app.schemas.equipment import (
    EquipmentCreateRequest,
    EquipmentPageResponse,
    EquipmentResponse,
    EquipmentUpdateRequest,
)
from app.schemas.lab import (
    LabCreateRequest,
    LabPageResponse,
    LabResponse,
    LabUpdateRequest,
)
from app.schemas.reservation import (
    ReservationPageResponse,
    ReservationReviewRequest,
    reservation_response,
)
from app.schemas.user import (
    ResetPasswordRequest,
    UserPageResponse,
    UserResponse,
    UserRoleUpdateRequest,
    UserStatusUpdateRequest,
)
from app.services import (
    equipment_service,
    lab_service,
    reservation_service,
    user_service,
)

router = APIRouter(prefix="/admin", tags=["管理员接口"])


@router.get("/user/list")
def list_users(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数"),
    keyword: str | None = Query(None, description="按账号或姓名模糊搜索"),
    role: str | None = Query(None, description="按角色筛选"),
    status: int | None = Query(None, description="按状态筛选：0-禁用，1-正常"),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """分页查询用户列表

    `_: User = Depends(get_current_admin)` 这个下划线参数本身用不到，
    挂在这里纯粹是为了让整个接口走一遍管理员校验——接口的准入条件写在
    函数签名里，比写在函数体内的 if 更难漏掉。
    """
    total, items = user_service.list_users_page(
        db, page, page_size, keyword, role, status
    )

    return Response.success(
        data=UserPageResponse(
            total=total,
            page=page,
            page_size=page_size,
            # UserResponse 里没有 password 字段，列表接口不会带出密码密文
            items=[UserResponse.model_validate(item) for item in items],
        )
    )


@router.put("/user/{user_id}/role")
def update_user_role(
    user_id: int,
    data: UserRoleUpdateRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """修改指定用户的角色

    不允许改自己角色的理由、以及"多个管理员互相降级"这个已知缺口，
    都写在 user_service.update_user_role 里。
    """
    user = user_service.update_user_role(db, current_admin, user_id, data.role)

    return Response.success(
        message="角色已更新", data=UserResponse.model_validate(user)
    )


@router.put("/user/{user_id}/status")
def update_user_status(
    user_id: int,
    data: UserStatusUpdateRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """启用 / 禁用指定用户

    不允许禁用自己、以及"禁用后对方的 token 会立刻失效"的原理，
    见 user_service.update_user_status。
    """
    user = user_service.update_user_status(db, current_admin, user_id, data.status)

    action = "已启用" if data.status == 1 else "已禁用"
    return Response.success(message=f"账号{action}", data=UserResponse.model_validate(user))


@router.put("/user/{user_id}/password")
def reset_user_password(
    user_id: int,
    data: ResetPasswordRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """重置指定用户的密码

    为什么重置不需要验原密码（而"改密码"要），见 user_service.reset_user_password。
    """
    user_service.reset_user_password(db, user_id, data.new_password)

    return Response.success(message="密码已重置")


# ============ 实验室管理 ============


@router.get("/lab/list")
def admin_list_labs(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数"),
    keyword: str | None = Query(None, description="按名称、房间号或楼栋模糊搜索"),
    category: str | None = Query(None, description="按类别筛选"),
    status: str | None = Query(None, description="按状态筛选"),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """分页查询实验室（管理端）"""
    total, items = lab_service.list_labs_page(
        db, page, page_size, keyword, category, status
    )

    return Response.success(
        data=LabPageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[LabResponse.model_validate(item) for item in items],
        )
    )


@router.post("/lab")
def create_lab(
    data: LabCreateRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """新增实验室

    房间号查重、以及并发插入时靠唯一索引兜底的处理，见 lab_service.create_lab。
    """
    lab = lab_service.create_lab(db, data)

    return Response.success(
        message="实验室已创建", data=LabResponse.model_validate(lab)
    )


@router.put("/lab/{lab_id}")
def update_lab(
    lab_id: int,
    data: LabUpdateRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """修改实验室（全量更新）

    查重时要把实验室自己排除掉（否则改其它字段会被自己的房间号挡住），
    这个处理在 lab_service.update_lab 里。
    """
    lab = lab_service.update_lab(db, lab_id, data)

    return Response.success(
        message="实验室已更新", data=LabResponse.model_validate(lab)
    )


@router.delete("/lab/{lab_id}")
def delete_lab(
    lab_id: int,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """没有预约记录时删除实验室及其设备。"""
    equipment_count = lab_service.delete_lab(db, lab_id)

    message = "实验室已删除"
    if equipment_count:
        message = f"实验室及其 {equipment_count} 种设备已删除"

    return Response.success(message=message)


# ============ 设备管理 ============


@router.get("/equipment/list")
def admin_list_equipments(
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数"),
    lab_id: int | None = Query(None, description="只查某间实验室的设备"),
    keyword: str | None = Query(None, description="按设备名称或型号模糊搜索"),
    status: str | None = Query(None, description="按状态筛选"),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """分页查询设备（管理端）

    lab_id 可选参数的语义、以及型号为空时不命中的原因，
    见 equipment_service.list_equipments_page。
    """
    total, items = equipment_service.list_equipments_page(
        db, page, page_size, lab_id, keyword, status
    )

    return Response.success(
        data=EquipmentPageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[EquipmentResponse.model_validate(item) for item in items],
        )
    )


@router.post("/equipment")
def create_equipment(
    data: EquipmentCreateRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """新增设备

    先确认实验室存在（否则外键约束抛出的是 500，而这里能给人话 404），
    理由见 lab_service.get_lab_or_404。
    """
    equipment = equipment_service.create_equipment(db, data)

    return Response.success(
        message="设备已新增", data=EquipmentResponse.model_validate(equipment)
    )


@router.put("/equipment/{equipment_id}")
def update_equipment(
    equipment_id: int,
    data: EquipmentUpdateRequest,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """修改设备（全量更新）

    lab_id 也是全量更新的一部分，所以设备可以被改挂到另一间实验室。
    """
    equipment = equipment_service.update_equipment(db, equipment_id, data)

    return Response.success(
        message="设备已更新", data=EquipmentResponse.model_validate(equipment)
    )


@router.delete("/equipment/{equipment_id}")
def delete_equipment(
    equipment_id: int,
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """删除设备；预约当前只关联实验室，不单独关联设备。"""
    equipment_service.delete_equipment(db, equipment_id)

    return Response.success(message="设备已删除")


# ============ 预约审核 ============


@router.get("/reservation/list")
def admin_list_reservations(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: str | None = Query(None, description="预约状态"),
    keyword: str | None = Query(None, description="实验室、房间号或申请人"),
    _: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    total, items = reservation_service.list_reservations_page(
        db, page, page_size, status, keyword
    )

    return Response.success(
        data=ReservationPageResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=[reservation_response(item) for item in items],
        )
    )


@router.put("/reservation/{reservation_id}/review")
def review_reservation(
    reservation_id: int,
    data: ReservationReviewRequest,
    current_admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    reservation = reservation_service.review_reservation(
        db, current_admin, reservation_id, data
    )

    message = "预约已通过" if data.status == "approved" else "预约已驳回"
    return Response.success(message=message, data=reservation_response(reservation))
