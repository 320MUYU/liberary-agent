from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.agent import runtime
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user


router = APIRouter(prefix="/agent", tags=["图书借阅助手"])


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    query: str = Field(min_length=1, max_length=1000)


class SelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    book_id: int = Field(gt=0, strict=True)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: UUID
    confirmed: StrictBool


@router.post("/runs")
def start(data: StartRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.start_run(db, user.id, str(data.request_id), data.query))


@router.get("/runs/{run_id}")
def view(run_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id)))


@router.post("/runs/{run_id}/select")
def select(run_id: UUID, data: SelectRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id), "select", data.model_dump()))


@router.post("/runs/{run_id}/decision")
def decide(run_id: UUID, data: DecisionRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id), "decision", data.model_dump(mode="json")))


@router.post("/runs/{run_id}/retry")
def retry(run_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=runtime.run_graph(db, user.id, str(run_id), "retry"))
