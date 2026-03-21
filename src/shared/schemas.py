from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TargetType(str, Enum):
    TOOL = "tool"
    AGENT = "agent"
    WORKFLOW = "workflow"
    FALLBACK = "fallback"


class StepType(str, Enum):
    AGENT = "agent"
    MARKDOWN_TASK = "markdown_task"
    AGENT_TASK = "agent_task"


class MatchType(str, Enum):
    CONTAINS_ANY = "contains_any"
    FALLBACK = "fallback"


class ExposureMode(str, Enum):
    INTERNAL_WORKER = "internal_worker"
    HUB_ADDRESSABLE = "hub_addressable"
    STANDALONE_TELEGRAM = "standalone_telegram"


class ExecutionMode(str, Enum):
    NATIVE_HUB = "native_hub"
    EXTERNAL_ADAPTER = "external_adapter"
    EXTERNAL_PASSTHROUGH = "external_passthrough"


class AdapterType(str, Enum):
    NATIVE = "native"
    PYTHON_PROCESS = "python_process"
    TELEGRAM_BOT = "telegram_bot"
    OPENCLAW = "openclaw"
    CUSTOM = "custom"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NormalizedEvent(BaseModel):
    source: str
    external_id: str
    thread_id: str
    user_payload: dict[str, Any]
    text: str
    received_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentSpec(BaseModel):
    id: str
    purpose: str
    prompt_file: str
    soul_file: str | None = None
    loadout_id: str | None = None
    exposure_mode: ExposureMode = ExposureMode.INTERNAL_WORKER
    execution_mode: ExecutionMode = ExecutionMode.NATIVE_HUB
    adapter_type: AdapterType | str = AdapterType.NATIVE
    adapter_config: dict[str, Any] = Field(default_factory=dict)
    telegram_profile_id: str | None = None
    can_receive_tasks: bool = True
    can_receive_messages: bool = False
    telegram: dict[str, Any] = Field(default_factory=dict)
    skill_ids: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    preferred_model: str
    memory_scope: str = "session"
    timeout: int = 30
    enabled: bool = True


class SkillSpec(BaseModel):
    id: str
    name: str
    markdown_file: str
    description: str
    enabled: bool = True


class ToolSpec(BaseModel):
    id: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    side_effect_level: str = "none"
    permissions: list[str] = Field(default_factory=list)
    enabled: bool = True


class ModelSpec(BaseModel):
    id: str
    provider: str
    model_name: str
    timeout: int = 30
    defaults: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class WorkflowStep(BaseModel):
    type: StepType
    target_id: str | None = None
    source_agent: str | None = None
    target_agent: str | None = None
    intent: str | None = None


class WorkflowSpec(BaseModel):
    id: str
    steps: list[WorkflowStep]
    timeout: int = 60
    enabled: bool = True


class RouteMatch(BaseModel):
    type: MatchType
    values: list[str] = Field(default_factory=list)


class RoutingRule(BaseModel):
    id: str
    match: RouteMatch
    target_type: TargetType
    target_id: str
    reason: str


class RouteDecision(BaseModel):
    matched_rule: str
    target_type: TargetType
    target_id: str
    reason: str
    config_version: str


class AgentContext(BaseModel):
    run_id: str
    event: NormalizedEvent
    allowed_tools: list[str]
    model_id: str
    prompt_text: str
    resolved_skills: list[str]
    workspace_path: str
    agent_id: str | None = None


class ToolResult(BaseModel):
    tool_id: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentResult(BaseModel):
    agent_id: str
    output_text: str
    tool_results: list[ToolResult] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTaskRecord(BaseModel):
    task_id: str
    created_by: str
    assigned_to: str
    goal: str
    input_context: str
    status: TaskStatus = TaskStatus.QUEUED
    result_summary: str = ""
    result_payload: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    artifacts: list[str] = Field(default_factory=list)
    adapter_type: str = "native"
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AdapterHealth(BaseModel):
    adapter_type: str
    agent_id: str
    status: Literal["ok", "degraded", "unavailable"]
    details: dict[str, Any] = Field(default_factory=dict)


class WorkflowResult(BaseModel):
    workflow_id: str
    status: Literal["completed", "failed"]
    final_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarkdownTaskFile(BaseModel):
    task_id: str
    source_agent: str
    target_agent: str
    intent: str
    constraints: list[str] = Field(default_factory=list)
    input_context: str
    status: Literal["pending", "completed"] = "pending"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MarkdownResultFile(BaseModel):
    task_id: str
    producing_agent: str
    summary: str
    artifacts: list[str] = Field(default_factory=list)
    next_step_hints: list[str] = Field(default_factory=list)
    status: Literal["completed"] = "completed"
    created_at: datetime = Field(default_factory=utc_now)


class RunTrace(BaseModel):
    run_id: str
    route: RouteDecision
    prompt_files: list[str] = Field(default_factory=list)
    skill_files: list[str] = Field(default_factory=list)
    markdown_handoffs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    created_at: datetime = Field(default_factory=utc_now)


class ManagementAction(BaseModel):
    actor: str
    action: str
    target: str
    params: dict[str, Any] = Field(default_factory=dict)
    result: str
    timestamp: datetime = Field(default_factory=utc_now)
    audit_id: str


class HubConfig(BaseModel):
    name: str
    paused: bool = False
    default_agent: str
    log_level: str = "INFO"
    sqlite_path: str
    structured_log_path: str
    human_log_path: str
    state_path: str
    pid_path: str


class TelegramConfig(BaseModel):
    enabled: bool = True
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    allowed_chat_ids: list[str] = Field(default_factory=list)


class HubFileConfig(BaseModel):
    environment: str = "development"
    hub: HubConfig
    telegram: TelegramConfig


class ManagementConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8011
    audit_actor: str = "operator"
    allow_prompt_edits: bool = True
    allow_skill_edits: bool = True
