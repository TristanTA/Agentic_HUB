from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agentic_hub.models.admin_action import AdminAction


OperatorIntent = Literal[
    "read_only_lookup",
    "single_step_mutation",
    "multi_step_operator_task",
    "approval_gated_change",
]

OperatorGoalType = Literal[
    "generic_admin_help",
    "create_worker",
    "create_tool",
    "attach_managed_bot",
    "enable_worker_capability",
    "set_up_scheduled_reminders",
    "improve_worker_configuration",
    "configure_group_access",
    "prepare_code_change_request",
    "read_only_lookup",
]


class OperatorPlanStep(BaseModel):
    step_id: str
    summary: str
    status: Literal["planned", "blocked", "ready", "completed"] = "planned"
    actions: list[AdminAction] = Field(default_factory=list)


class OperatorGoalPlan(BaseModel):
    goal_type: OperatorGoalType
    intent: OperatorIntent
    goal_summary: str
    user_response: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    chosen_defaults: dict[str, str] = Field(default_factory=dict)
    missing_essentials: list[str] = Field(default_factory=list)
    steps: list[OperatorPlanStep] = Field(default_factory=list)
    action_groups: list[list[AdminAction]] = Field(default_factory=list)
    requires_approval: bool = False
    reply_only: bool = False


class OperatorFollowUpState(BaseModel):
    goal_type: OperatorGoalType
    original_text: str
    current_stage: str
    unresolved_questions: list[str] = Field(default_factory=list)
    inferred_defaults: dict[str, str] = Field(default_factory=dict)
    accumulated_answers: dict[str, str] = Field(default_factory=dict)
    drafted_action_groups: list[list[AdminAction]] = Field(default_factory=list)
    user_response_prefix: str | None = None
