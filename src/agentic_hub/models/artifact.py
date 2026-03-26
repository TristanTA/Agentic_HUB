from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Artifact(BaseModel):
    artifact_id: str
    task_id: str
    worker_id: str
    kind: str = Field(..., description="message, file, report, plan, patch, approval_request")
    title: str = ""
    content: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
