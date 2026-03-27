from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LiveWorkflow(BaseModel):
    workflow_id: str
    target_worker_id: str
    objective: str
    status: str = Field(
        default="queued",
        description="queued, researching, awaiting_approval, applying, verifying, completed, failed, rejected",
    )
    research_worker_id: str
    operator_worker_id: str
    requested_by_user_id: str | None = None
    requested_from_chat_id: str | None = None
    research_task_id: str | None = None
    implementation_task_id: str | None = None
    verification_task_id: str | None = None
    research_artifact_id: str | None = None
    change_set_artifact_id: str | None = None
    verification_artifact_id: str | None = None
    approval_id: str | None = None
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
