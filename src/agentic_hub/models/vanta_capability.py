from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agentic_hub.models.admin_action import AdminActionKind


CapabilityAccess = Literal["read", "mutating"]
CapabilityPack = Literal["default", "repo", "web", "operator"]


class VantaCapability(BaseModel):
    capability_id: str
    label: str
    summary: str
    action_kind: AdminActionKind | None = None
    access: CapabilityAccess
    required_argument_names: list[str] = Field(default_factory=list)
    escalation_pack: CapabilityPack = "default"
