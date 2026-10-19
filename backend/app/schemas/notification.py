from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class NotificationResponse(BaseModel):
    id: int
    kind: str
    title: str
    content: str
    resource_type: Literal["loan", "reservation"]
    resource_id: int
    create_time: datetime
    read_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class NotificationPageResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int
    max_id: int


class ReadAllNotifications(BaseModel):
    through_id: int = Field(ge=0, strict=True)
