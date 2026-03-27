from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


AdminActionKind = Literal[
    "create_worker",
    "update_worker",
    "create_loadout",
    "create_tool",
    "grant_tool_access",
    "attach_managed_bot",
    "propose_skill",
    "approve_skill",
    "reject_skill",
    "attach_skill_to_loadout",
    "list_skills",
    "review_skills",
    "start_bot",
    "stop_bot",
    "run_smoke_test",
    "inspect_status",
    "list_objects",
    "list_services",
    "request_code_change",
]


class AdminAction(BaseModel):
    kind: AdminActionKind
    params: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    requires_approval: bool = False
    validation_steps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_required_fields(self) -> "AdminAction":
        required_params = {
            "create_worker": {"worker_id", "name", "type_id", "role_id", "loadout_id", "interface_mode"},
            "update_worker": {"worker_id", "updates"},
            "create_loadout": {"loadout_id", "name"},
            "create_tool": {"tool_id", "name", "description", "implementation_ref"},
            "grant_tool_access": {"worker_id", "tool_id"},
            "attach_managed_bot": {"worker_id", "bot_token"},
            "propose_skill": {"request_text", "target_loadout_ids"},
            "approve_skill": {"skill_id"},
            "reject_skill": {"skill_id"},
            "attach_skill_to_loadout": {"skill_id", "loadout_id"},
            "list_skills": set(),
            "review_skills": set(),
            "start_bot": {"worker_id"},
            "stop_bot": {"worker_id"},
            "run_smoke_test": {"worker_id"},
            "inspect_status": {"target"},
            "list_objects": {"kind"},
            "list_services": set(),
            "request_code_change": {"request_summary"},
        }
        missing = sorted(required_params[self.kind] - set(self.params))
        if missing:
            raise ValueError(f"Missing params for {self.kind}: {', '.join(missing)}")
        return self


class AdminActionResult(BaseModel):
    kind: AdminActionKind
    status: Literal["completed", "approval_required", "failed"]
    summary: str
    changed_ids: list[str] = Field(default_factory=list)
    validation_results: list[str] = Field(default_factory=list)
    error: str | None = None


class AdminExecutionResult(BaseModel):
    status: Literal["completed", "approval_required", "failed"]
    summary: str
    action_results: list[AdminActionResult] = Field(default_factory=list)
    follow_up_question: str | None = None


class VantaPlan(BaseModel):
    actions: list[AdminAction] = Field(default_factory=list)
    follow_up_question: str | None = None
    follow_up_field: str | None = None
    pending_action_kind: AdminActionKind | None = None
    reply: str | None = None
