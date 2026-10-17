from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.agent import workflow
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.services.space_discovery import SpaceConditions


router = APIRouter(prefix="/workflows", tags=["组合任务助手"])


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    query: str = Field(min_length=1, max_length=1000)
    conditions: SpaceConditions | None = None


class ConditionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conditions: SpaceConditions


class ClarifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=1000)


class StepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: int = Field(strict=True, gt=0)
    operation: Literal["select", "select_loan", "select_space", "decision", "loans_page", "spaces_page", "skip"]
    book_id: int | None = Field(default=None, strict=True, gt=0)
    loan_id: int | None = Field(default=None, strict=True, gt=0)
    space_id: int | None = Field(default=None, strict=True, gt=0)
    page: int | None = Field(default=None, strict=True, ge=1, le=10000)
    action_id: UUID | None = None
    confirmed: StrictBool | None = None

    @model_validator(mode="after")
    def bound_arguments(self):
        required = {"select": {"book_id"}, "select_loan": {"loan_id"}, "select_space": {"space_id"},
            "decision": {"action_id", "confirmed"}, "loans_page": {"page"}, "spaces_page": {"page"}, "skip": set()}[self.operation]
        supplied = self.model_fields_set - {"step_id", "operation"}
        if supplied != required or any(getattr(self, key) is None for key in required):
            raise ValueError("步骤参数与操作不匹配")
        return self


@router.post("")
def start(data: StartRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=workflow.create_workflow(db, user.id, str(data.request_id), data.query, data.conditions))


@router.get("/{workflow_id}")
def view(workflow_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=workflow.operate(db, user.id, str(workflow_id)))


@router.post("/{workflow_id}/retry")
def retry(workflow_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=workflow.operate(db, user.id, str(workflow_id), "retry"))


@router.post("/{workflow_id}/cancel")
def cancel(workflow_id: UUID, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=workflow.operate(db, user.id, str(workflow_id), "cancel"))


@router.post("/{workflow_id}/conditions")
def conditions(workflow_id: UUID, data: ConditionsRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=workflow.operate(db, user.id, str(workflow_id), "conditions", data.model_dump(mode="json")))


@router.post("/{workflow_id}/clarify")
def clarify(workflow_id: UUID, data: ClarifyRequest, user=Depends(get_current_user), db=Depends(get_db)):
    return Response.success(data=workflow.operate(db, user.id, str(workflow_id), "clarify", data.model_dump()))


@router.post("/{workflow_id}/steps")
def step(workflow_id: UUID, data: StepRequest, user=Depends(get_current_user), db=Depends(get_db)):
    payload = data.model_dump(mode="json", exclude_unset=True)
    operation = payload.pop("operation")
    return Response.success(data=workflow.operate(db, user.id, str(workflow_id), operation, payload))
