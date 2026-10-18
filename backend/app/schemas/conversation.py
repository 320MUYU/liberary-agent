"""Public messages never carry user identity or implicit business confirmation."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.workflow import WorkflowPlan
from app.schemas.reservation import TIME_PATTERN


class CreateConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: UUID
    text: str = Field(min_length=1, max_length=1000)
    hint: Literal["auto", "chat", "knowledge", "library", "space"] = "auto"


class ConditionsDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    date_expression: str | None = Field(default=None, min_length=1, max_length=40)
    start: str | None = Field(default=None, pattern=TIME_PATTERN)
    end: str | None = Field(default=None, pattern=TIME_PATTERN)
    people: int | None = Field(default=None, strict=True, ge=1, le=1000)
    purpose: str | None = Field(default=None, min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=200)


class ConversationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["plan", "ask", "supplement", "conditions"]
    plan: WorkflowPlan | None = None
    workflow_id: UUID | None = None
    message: str | None = Field(default=None, min_length=1, max_length=500)
    draft: ConditionsDraft | None = None

    @model_validator(mode="after")
    def bound_route(self):
        if self.action == "plan":
            if self.plan is None or self.workflow_id is not None or self.message is not None:
                raise ValueError("新任务必须提供计划")
        elif self.action == "ask":
            if self.message is None or self.plan is not None or self.workflow_id is not None or self.draft is not None:
                raise ValueError("澄清必须只提供问题")
        elif self.action == "supplement":
            if self.workflow_id is None or self.message is None or self.plan is not None or self.draft is not None:
                raise ValueError("补充需求必须绑定已有任务")
        elif self.workflow_id is None or self.draft is None or self.plan is not None or self.message is not None:
            raise ValueError("补充条件必须绑定已有任务")
        return self

