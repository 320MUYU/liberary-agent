from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class ImportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=150)
    report: dict


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: int = Field(strict=True, ge=0)
    status: Literal["draft", "reviewed"] = "draft"
    answer_correct: StrictBool | None = None
    citations_support: StrictBool | None = None
    notes: str = Field(default="", max_length=10000)

    @model_validator(mode="after")
    def completed_judgment(self):
        if self.status == "reviewed" and (self.answer_correct is None or self.citations_support is None):
            raise ValueError("提交审核前必须明确选择回答正确性和引用支持性")
        return self

