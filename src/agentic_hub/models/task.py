from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Task(BaseModel):
    task_id: str
    kind: str
    payload: Dict[str, Any] = Field(default_factory=dict)

    status: str = Field(
        default="queued",
        description="queued, running, waiting_approval, done, failed, cancelled",
    )

    target_worker_id: Optional[str] = None
    target_role_id: Optional[str] = None

    priority: int = 0
    created_at: datetime = Field(default_factory=utc_now)
    next_run_at: datetime = Field(default_factory=utc_now)

    retries: int = 0
    max_retries: int = 3

    approval_required: bool = False
    required_tool_ids: list[str] = Field(default_factory=list)
    required_memory_types: list[str] = Field(default_factory=list)

    session_id: Optional[str] = None
    run_group_id: Optional[str] = None
    correlation_id: Optional[str] = None
