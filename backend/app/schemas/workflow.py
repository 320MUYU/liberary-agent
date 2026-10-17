"""Plans contain task descriptions only; identity and confirmations stay server-owned."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkflowTask(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    task_type: Literal["borrow", "my_loans", "return", "reservation"]
    query: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=80)
    read_only: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def personal_query_is_read_only(self):
        if self.task_type == "my_loans":
            self.read_only = True
        return self


class WorkflowPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    steps: list[WorkflowTask] = Field(max_length=3)
    clarification: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def steps_or_clarification(self):
        if bool(self.steps) == bool(self.clarification):
            raise ValueError("必须提供任务步骤或一个澄清问题")
        return self
