from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalRequest(BaseModel):
    approval_id: str
    task_id: str
    requested_by_worker_id: str
    requested_for_worker_id: Optional[str] = None

    title: str
    summary: str
    risk_level: str = Field(default="medium", description="low, medium, high")
    channel: str = "telegram"

    status: str = Field(
        default="pending",
        description="pending, approved, rejected, expired, modified",
    )

    created_at: datetime = Field(default_factory=utc_now)
    responded_at: Optional[datetime] = None
    approver_id: Optional[str] = None
    response_note: Optional[str] = None
