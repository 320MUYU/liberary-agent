from typing import Literal

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_admin
from app.models.users import User
from app.schemas.evaluation_review import ImportReport, ReviewDecision
from app.services import evaluation_review_service as service


router = APIRouter(prefix="/admin/evaluation-reviews", tags=["AI效果审核"])


@router.get("")
def list_runs(_: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return Response.success(data=service.list_runs(db))


@router.post("/import")
def import_report(data: ImportReport, admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return Response.success(data=service.import_report(db, data.report, data.name, admin))


@router.get("/{run_id}")
def get_run(run_id: int = Path(ge=1),
            status: Literal["all", "pending", "reviewed", "human_negative", "automatic_failure"] = Query("all"),
            _: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return Response.success(data=service.get_run(db, run_id, status))


@router.get("/{run_id}/cases/{case_id}")
def get_case(case_id: str, run_id: int = Path(ge=1),
             _: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return Response.success(data=service.get_case(db, run_id, case_id))


@router.put("/{run_id}/cases/{case_id}")
def save_review(case_id: str, data: ReviewDecision, run_id: int = Path(ge=1),
                admin: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return Response.success(data=service.save_review(db, run_id, case_id, data, admin))


@router.get("/{run_id}/export/reviews")
def export_reviews(run_id: int = Path(ge=1), _: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return Response.success(data=service.export_reviews(db, run_id))


@router.get("/{run_id}/export/report")
def export_report(run_id: int = Path(ge=1), _: User = Depends(get_current_admin), db: Session = Depends(get_db)):
    return Response.success(data=service.export_report(db, run_id))
