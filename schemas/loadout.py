from pydantic import BaseModel, Field
from typing import Any, List
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Loadout(BaseModel):
    loadout_id: str
    name: str
    description: str = ""
    prompt_refs: List[str] = Field(default_factory=list)
    soul_ref: str | None = None
    skill_refs: List[str] = Field(default_factory=list)
    memory_policy_ref: str | None = None
    model_policy_ref: str | None = None
    approval_policy_ref: str | None = None
    artifact_policy_ref: str | None = None
    runtime_limits_ref: str | None = None
    allowed_tool_ids: List[str] = Field(default_factory=list)
    tool_policy_overrides: dict[str, Any] = Field(default_factory=dict)
    default_task_templates: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    source: str = Field(default="runtime", description="seed, runtime, package")
    package_id: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)
