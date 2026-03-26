from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HubEvent(BaseModel):
    event_id: str
    task_id: str | None = None
    worker_id: str | None = None
    event_type: str = Field(..., description="task_started, task_completed, task_failed, approval_requested, artifact_created")
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
