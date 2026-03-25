from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TaskResult(BaseModel):
    task_id: str
    worker_id: str
    status: str = Field(
        ...,
        description="done, failed, blocked, needs_approval, retry, cancelled",
    )
    summary: str = ""
    output_payload: Dict[str, Any] = Field(default_factory=dict)
    artifact_refs: List[str] = Field(default_factory=list)
    follow_up_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None
