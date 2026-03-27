from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowTaskRecord(BaseModel):
    task_id: str
    workflow_id: str
    kind: str
    target_worker_id: str | None = None
    assigned_worker_id: str | None = None
    status: str = Field(
        default="queued",
        description="queued, running, done, failed, needs_approval, blocked, rejected",
    )
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    follow_up_task_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
