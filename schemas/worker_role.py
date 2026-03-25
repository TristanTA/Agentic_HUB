from pydantic import BaseModel, Field
from typing import List


class WorkerRole(BaseModel):
    role_id: str
    name: str
    purpose: str
    behavior_guide_ref: str | None = None
    default_output_style: str | None = None
    default_handoff_targets: List[str] = Field(default_factory=list)
    allowed_action_patterns: List[str] = Field(default_factory=list)
    blocked_action_patterns: List[str] = Field(default_factory=list)
