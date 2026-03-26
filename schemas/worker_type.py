from pydantic import BaseModel, Field
from typing import Any, List
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkerType(BaseModel):
    type_id: str
    name: str
    execution_mode: str = Field(..., description="llm, deterministic, approval")
    can_use_tools: bool = True
    can_spawn_tasks: bool = False
    can_request_approval: bool = False
    can_emit_artifacts: bool = True
    default_retry_policy: dict[str, Any] = Field(default_factory=dict)
    allowed_task_kinds: List[str] = Field(default_factory=list)
    lifecycle_states: List[str] = Field(
        default_factory=lambda: ["idle", "running", "paused", "failed"]
    )
    source: str = Field(default="runtime", description="seed, runtime, package")
    package_id: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)
