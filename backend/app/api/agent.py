from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.agent import runtime
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.services.space_discovery import SpaceConditions


router = APIRouter(prefix="/agent", tags=["图书借阅助手"])


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    query: str = Field(min_length=1, max_length=1000)
    task_type: Literal["borrow", "my_loans", "return", "reservation"] = "borrow"
    conditions: SpaceConditions | None = None

    @model_validator(mode="after")
    def conditions_for_task(self):
        if (self.task_type == "reservation") != (self.conditions is not None):
            raise ValueError("空间预约需完整填写日期、时间、人数和用途；其他任务不接受预约条件")
        return self


class SelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    book_id: int = Field(gt=0, strict=True)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: UUID
    confirmed: StrictBool


class SelectLoanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    loan_id: int = Field(gt=0, strict=True)


class LoanPageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1, le=10000, strict=True)


class SelectSpaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    space_id: int = Field(gt=0, strict=True)


@router.post("/runs")
def start(data: StartRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.start_run(db, user.id, str(data.request_id), data.query, data.task_type,
        **({"conditions": data.conditions} if data.conditions is not None else {})))


@router.post("/runs/{run_id}/select-space")
def select_space(run_id: UUID, data: SelectSpaceRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id), "select_space", data.model_dump()))


@router.post("/runs/{run_id}/spaces-page")
def spaces_page(run_id: UUID, data: LoanPageRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id), "spaces_page", data.model_dump()))


@router.get("/runs/{run_id}")
def view(run_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id)))


@router.post("/runs/{run_id}/select")
def select(run_id: UUID, data: SelectRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id), "select", data.model_dump()))


@router.post("/runs/{run_id}/decision")
def decide(run_id: UUID, data: DecisionRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id), "decision", data.model_dump(mode="json")))


@router.post("/runs/{run_id}/select-loan")
def select_loan(run_id: UUID, data: SelectLoanRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id), "select_loan", data.model_dump()))


@router.post("/runs/{run_id}/loans-page")
def loans_page(run_id: UUID, data: LoanPageRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id), "loans_page", data.model_dump()))


@router.post("/runs/{run_id}/retry")
def retry(run_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id), "retry"))
