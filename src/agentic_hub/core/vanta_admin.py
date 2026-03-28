from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import requests

from agentic_hub.core.admin_executor import AdminExecutor
from agentic_hub.models.admin_action import AdminAction, AdminActionKind, AdminExecutionResult
from agentic_hub.models.operator_plan import OperatorFollowUpState, OperatorGoalPlan, OperatorPlanStep
from agentic_hub.models.vanta_capability import VantaCapability


TOKEN_PATTERN = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]+\b")
CREATE_WORDS = {"create", "make", "new", "add", "build"}
READ_ONLY_COMMANDS = {"help", "status", "workers", "tasks", "inspect", "logs"}
CANCEL_WORDS = {"cancel", "stop", "never mind", "nevermind", "abort"}
TECHNICAL_TERMS = {
    "tool",
    "tools",
    "loadout",
    "loadout_id",
    "role",
    "role_id",
    "worker_id",
    "runtime",
    "catalog",
    "repo",
    "prompt",
    "prompts",
    "skill",
    "skills",
    "implementation",
}
NEW_REQUEST_PREFIXES = {
    "what",
    "why",
    "how",
    "can",
    "could",
    "which",
    "show",
    "list",
    "inspect",
    "create",
    "make",
    "add",
    "give",
    "grant",
    "allow",
    "enable",
    "start",
    "stop",
    "help",
}


@dataclass(frozen=True)
class VantaSystemConfig:
    system_id: str = "vanta_system_admin"
    display_name: str = "Vanta"
    locked: bool = True
    default_packs: tuple[str, ...] = ("default",)
    escalation_packs: tuple[str, ...] = ("repo", "web", "operator")


@dataclass
class PendingAdminRequest:
    session_type: Literal["operator_follow_up", "skill_approval"]
    state: OperatorFollowUpState | None = None
    skill_id: str | None = None
    target_loadout_ids: list[str] | None = None
    blocker_key: str | None = None


class VantaAdminAgent:
    SYSTEM_CONFIG = VantaSystemConfig()
    _CAPABILITIES: tuple[VantaCapability, ...] = (
        VantaCapability(capability_id="inspect_hub_status", label="inspect hub status", summary="Read overall hub health and counts.", action_kind="inspect_status", access="read", required_argument_names=["target"]),
        VantaCapability(capability_id="list_workers", label="list workers", summary="Read worker inventory and interface modes.", action_kind="list_objects", access="read", required_argument_names=["kind"]),
        VantaCapability(capability_id="list_tasks", label="list tasks", summary="Read scheduled task inventory.", action_kind="list_objects", access="read", required_argument_names=["kind"]),
        VantaCapability(capability_id="list_services", label="list services", summary="Read registered services and states.", action_kind="list_services", access="read"),
        VantaCapability(capability_id="inspect_worker_tools", label="inspect worker tools", summary="Read a worker's allowed tools through its loadout.", action_kind="inspect_worker_tools", access="read", required_argument_names=["worker_id"]),
        VantaCapability(capability_id="inspect_worker_context", label="inspect worker context", summary="Read a worker's role, loadout, prompts, and skills.", action_kind="inspect_worker_context", access="read", required_argument_names=["worker_id"]),
        VantaCapability(capability_id="inspect_worker_delegation", label="inspect worker delegation", summary="Read which workers Vanta can lean on for implementation or research support.", action_kind="inspect_worker_delegation", access="read"),
        VantaCapability(capability_id="inspect_logs", label="inspect logs", summary="Review recent operational logs.", action_kind=None, access="read"),
        VantaCapability(capability_id="create_worker", label="create worker", summary="Create an internal or managed worker in runtime overrides and validate it.", action_kind="create_worker", access="mutating", required_argument_names=["worker_id", "name", "type_id", "role_id", "loadout_id", "interface_mode"]),
        VantaCapability(capability_id="create_tool", label="create tool", summary="Create a runtime tool definition for the hub catalog.", action_kind="create_tool", access="mutating", required_argument_names=["tool_id", "name", "description", "implementation_ref"]),
        VantaCapability(capability_id="grant_tool_access", label="grant tool access", summary="Grant an existing tool to a worker by updating its loadout.", action_kind="grant_tool_access", access="mutating", required_argument_names=["worker_id", "tool_id"]),
        VantaCapability(capability_id="attach_managed_bot", label="attach managed bot", summary="Attach a Telegram bot token to an existing managed worker.", action_kind="attach_managed_bot", access="mutating", required_argument_names=["worker_id", "bot_token"]),
        VantaCapability(capability_id="review_skills", label="review skills", summary="Generate a monthly skill review report.", action_kind="review_skills", access="read"),
        VantaCapability(capability_id="request_code_change", label="request code change", summary="Draft an approval-gated repo change proposal.", action_kind="request_code_change", access="mutating", required_argument_names=["request_summary"], escalation_pack="repo"),
        VantaCapability(capability_id="repo_context", label="repo context", summary="Fetch repo-oriented capability details when a task requires code changes.", action_kind=None, access="read", escalation_pack="repo"),
        VantaCapability(capability_id="web_context", label="web context", summary="Fetch web-oriented capability details when a task requires external research.", action_kind=None, access="read", escalation_pack="web"),
        VantaCapability(capability_id="operator_context", label="operator context", summary="Fetch broader operator capability details for privileged workflows.", action_kind=None, access="read", escalation_pack="operator"),
    )

    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self.executor = AdminExecutor(hub)
        self._sessions: dict[str, PendingAdminRequest] = {}

    @property
    def system_config(self) -> VantaSystemConfig:
        return self.SYSTEM_CONFIG

    def default_capabilities(self) -> list[VantaCapability]:
        return self.get_capability_manifest()

    def get_capability_manifest(self, packs: list[str] | None = None) -> list[VantaCapability]:
        requested = set(packs or list(self.SYSTEM_CONFIG.default_packs))
        if not requested:
            requested = set(self.SYSTEM_CONFIG.default_packs)
        capabilities = [item for item in self._CAPABILITIES if item.escalation_pack in requested]
        return sorted(capabilities, key=lambda item: (item.escalation_pack, item.capability_id))

    def handle_message(self, text: str, payload: dict[str, Any]) -> str:
        message = text.strip()
        session_key = self._session_key(payload)
        pending = self._sessions.get(session_key)

        if self._is_cancel_intent(message):
            if pending is not None:
                del self._sessions[session_key]
                return "Cancelled that pending flow. Send a fresh request when you want to continue."
            return "There is no pending Vanta flow to cancel."

        if pending is not None and self._looks_like_topic_switch(message, pending):
            del self._sessions[session_key]
            fresh = self._route_message(message)
            return self._prepend_fresh_start(self._execute_goal_plan(fresh, session_key))

        if pending is not None:
            return self._continue_session(session_key, message)

        plan = self._route_message(message)
        return self._execute_goal_plan(plan, session_key)

    def _route_message(self, text: str) -> OperatorGoalPlan:
        inspect_plan = self._investigation_route(text)
        if inspect_plan is not None:
            return inspect_plan

        read_plan = self._cheap_route(text)
        if read_plan is not None:
            return read_plan

        return self._build_operator_goal_plan(text)

    def _continue_session(self, session_key: str, answer: str) -> str:
        session = self._sessions[session_key]
        if session.session_type == "skill_approval":
            skill_id = str(session.skill_id)
            loadout_ids = list(session.target_loadout_ids or [])
            decision = answer.strip().lower()
            del self._sessions[session_key]
            if decision in {"approve", "approved", "yes", "y"}:
                result = self.executor.execute([AdminAction(kind="approve_skill", params={"skill_id": skill_id, "loadout_ids": loadout_ids}, summary=f"Approve skill {skill_id}")])
                return self._render_execution_result(result)
            if decision in {"reject", "rejected", "no", "n"}:
                result = self.executor.execute([AdminAction(kind="reject_skill", params={"skill_id": skill_id}, summary=f"Reject skill {skill_id}")])
                return self._render_execution_result(result)
            self._sessions[session_key] = session
            return "Please reply `approve` or `reject`, or say `cancel` to exit this approval."

        if session.state is None:
            del self._sessions[session_key]
            return "I lost the operator context for that request. Please send it again."

        combined_request = self._merge_follow_up(
            original_request=session.state.original_text,
            answer=answer,
            blocker_key=session.blocker_key,
        )
        del self._sessions[session_key]
        resumed_plan = self._route_message(combined_request)
        return self._execute_goal_plan(resumed_plan, session_key)

    def _investigation_route(self, text: str) -> OperatorGoalPlan | None:
        lowered = text.lower().strip()
        if not lowered:
            return OperatorGoalPlan(
                goal_type="generic_admin_help",
                intent="read_only_lookup",
                goal_summary="General admin help",
                user_response=self._fallback_reply(text),
                reply_only=True,
            )

        detail_level = self._detail_level(text)
        worker_id = self._match_worker_id(text)

        if worker_id and self._is_worker_tools_question(lowered):
            actions = [[AdminAction(kind="inspect_worker_tools", params={"worker_id": worker_id, "detail_level": detail_level}, summary=f"Inspect tools for {worker_id}")]]
            return OperatorGoalPlan(
                goal_type="read_only_lookup",
                intent="read_only_lookup",
                goal_summary=f"Inspect tools for {worker_id}",
                user_response=self._worker_tools_intro(worker_id, detail_level),
                steps=[OperatorPlanStep(step_id="inspect_worker_tools", summary="Inspect worker tools", status="ready", actions=actions[0])],
                action_groups=actions,
            )

        if worker_id and self._is_worker_context_question(lowered):
            actions = [[AdminAction(kind="inspect_worker_context", params={"worker_id": worker_id, "detail_level": detail_level}, summary=f"Inspect context for {worker_id}")]]
            return OperatorGoalPlan(
                goal_type="read_only_lookup",
                intent="read_only_lookup",
                goal_summary=f"Inspect context for {worker_id}",
                user_response=self._worker_context_intro(worker_id, detail_level),
                steps=[OperatorPlanStep(step_id="inspect_worker_context", summary="Inspect worker context", status="ready", actions=actions[0])],
                action_groups=actions,
            )

        if self._is_delegation_question(lowered):
            actions = [[AdminAction(kind="inspect_worker_delegation", params={"detail_level": detail_level}, summary="Inspect Vanta delegation options")]]
            return OperatorGoalPlan(
                goal_type="read_only_lookup",
                intent="read_only_lookup",
                goal_summary="Inspect delegation options",
                user_response="I checked who Vanta can lean on internally for support.",
                steps=[OperatorPlanStep(step_id="inspect_worker_delegation", summary="Inspect delegation options", status="ready", actions=actions[0])],
                action_groups=actions,
            )

        capability_plan = self._inspect_worker_capability_plan(text)
        if capability_plan is not None:
            return capability_plan

        return None

    def _build_operator_goal_plan(self, text: str) -> OperatorGoalPlan:
        llm_plan = self._plan_with_llm(text)
        if llm_plan is not None:
            return llm_plan
        return self._plan_with_rules(text)

    def _plan_with_llm(self, text: str) -> OperatorGoalPlan | None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        packs = self._packs_for_text(text)
        manifest = self._manifest_prompt(packs)
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are Vanta, the Agentic Hub admin operator. "
                                "Investigate first, summarize your findings, then act. "
                                "Ask for at most one missing decision at a time. "
                                "Prefer runtime-safe changes when possible and explain why a code change is needed when it is not. "
                                "Return valid JSON for OperatorGoalPlan.\n\n"
                                f"{manifest}"
                            ),
                        },
                        {"role": "user", "content": text},
                    ],
                },
                timeout=45,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            raw = str(content) if not isinstance(content, list) else "\n".join(str(item.get("text", "")) for item in content)
            return OperatorGoalPlan.model_validate(json.loads(raw))
        except Exception:
            return None

    def _plan_with_rules(self, text: str) -> OperatorGoalPlan:
        lowered = text.lower().strip()
        if any(lowered.startswith(f"/{name}") for name in READ_ONLY_COMMANDS):
            return OperatorGoalPlan(
                goal_type="read_only_lookup",
                intent="read_only_lookup",
                goal_summary="Use slash command directly",
                user_response="Use the slash command directly for that operational check.",
                reply_only=True,
            )

        if self._is_create_tool_request(lowered):
            return self._low_level_tool_plan(text)

        if self._is_explicit_skill_request(text):
            target_loadout_ids = [self._seed_worker_draft(text).get("loadout_id", "operator_core")]
            actions = [[AdminAction(kind="propose_skill", params={"request_text": text, "target_loadout_ids": target_loadout_ids, "explicit": True}, summary="Draft reusable skill proposal")]]
            return OperatorGoalPlan(
                goal_type="improve_worker_configuration",
                intent="single_step_mutation",
                goal_summary="Draft reusable skill",
                user_response="I'm turning that into a reusable skill proposal and I'll bring it back for approval.",
                steps=[OperatorPlanStep(step_id="propose_skill", summary="Draft skill proposal", status="ready", actions=actions[0])],
                action_groups=actions,
            )

        if self._looks_like_scheduled_reminder_request(lowered):
            return self._reminder_goal_plan(text)

        worker_upgrade_plan = self._plan_worker_capability_request(text)
        if worker_upgrade_plan is not None:
            return worker_upgrade_plan

        start_stop_plan = self._plan_start_or_stop_bot(text)
        if start_stop_plan is not None:
            return start_stop_plan

        if "attach" in lowered and "bot" in lowered:
            draft = self._seed_worker_draft(text)
            missing = self._missing_fields_for("attach_managed_bot", draft)
            summary = f"Attach managed bot for {draft.get('worker_id', 'worker')}"
            response = f"I checked the request and can attach a managed bot for `{draft.get('worker_id', 'that worker')}` once I have the token."
            return self._single_step_goal("attach_managed_bot", "single_step_mutation", summary, response, draft, missing, source_request=text)

        tool_access_plan = self._plan_tool_access(text)
        if tool_access_plan is not None:
            return tool_access_plan

        if self._is_create_worker_request(lowered):
            draft = self._seed_worker_draft(text)
            missing = self._missing_fields_for("create_worker", draft)
            response = self._create_worker_intro(draft, lowered)
            return self._single_step_goal(
                goal_type="create_worker",
                intent="single_step_mutation",
                goal_summary=f"Create worker {draft.get('worker_id', 'worker')}",
                user_response=response,
                draft=draft,
                missing=missing,
                source_request=text,
            )

        worker_id = self._match_worker_id(text)
        if worker_id and any(word in lowered for word in {"improve", "better", "upgrade", "refine"}):
            return OperatorGoalPlan(
                goal_type="improve_worker_configuration",
                intent="multi_step_operator_task",
                goal_summary=f"Improve configuration for {worker_id}",
                user_response=f"I checked `{worker_id}` and I can help improve it. What outcome do you want most right now?",
                chosen_defaults={"worker_id": worker_id, "source_request": text},
                missing_essentials=["improvement_target"],
                reply_only=True,
            )

        if self._looks_like_repeated_skill_gap(text):
            gap_record = self.hub.skill_library.record_gap(text, explicit=False)
            if self.hub.skill_library.should_propose(gap_record, explicit=False):
                target_loadout_ids = [self._seed_worker_draft(text).get("loadout_id", "operator_core")]
                actions = [[AdminAction(kind="propose_skill", params={"request_text": text, "target_loadout_ids": target_loadout_ids, "explicit": False}, summary="Draft reusable skill proposal from repeated demand")]]
                return OperatorGoalPlan(
                    goal_type="improve_worker_configuration",
                    intent="single_step_mutation",
                    goal_summary="Draft reusable skill from repeated demand",
                    user_response="This keeps coming up, so I'm drafting a reusable skill proposal for approval.",
                    steps=[OperatorPlanStep(step_id="propose_skill", summary="Draft skill proposal", status="ready", actions=actions[0])],
                    action_groups=actions,
                )
            return OperatorGoalPlan(
                goal_type="generic_admin_help",
                intent="read_only_lookup",
                goal_summary="Acknowledge repeated demand",
                user_response="I noted that recurring need. If it keeps coming up, I'll draft a reusable skill for approval.",
                reply_only=True,
            )

        return OperatorGoalPlan(
            goal_type="generic_admin_help",
            intent="read_only_lookup",
            goal_summary="General admin help",
            user_response=self._fallback_reply(text),
            reply_only=True,
        )

    def _cheap_route(self, text: str) -> OperatorGoalPlan | None:
        lowered = text.lower().strip()
        if not lowered:
            return OperatorGoalPlan(goal_type="generic_admin_help", intent="read_only_lookup", goal_summary="General admin help", user_response=self._fallback_reply(text), reply_only=True)

        action_groups: list[list[AdminAction]] = []
        overview = self._overview_actions(lowered)
        if overview:
            action_groups = [overview]
        elif self._is_worker_listing_request(lowered):
            action_groups = [[AdminAction(kind="list_objects", params={"kind": "workers"}, summary="List workers")]]
        elif self._is_task_listing_request(lowered):
            action_groups = [[AdminAction(kind="list_objects", params={"kind": "tasks"}, summary="List tasks")]]
        elif self._is_service_listing_request(lowered):
            action_groups = [[AdminAction(kind="list_services", params={}, summary="List services")]]
        elif self._is_skill_listing_request(lowered):
            action_groups = [[AdminAction(kind="list_skills", params={}, summary="List skills")]]
        elif self._is_skill_review_request(lowered):
            action_groups = [[AdminAction(kind="review_skills", params={}, summary="Generate skill review report")]]
        elif self._is_hub_status_request(lowered):
            action_groups = [[AdminAction(kind="inspect_status", params={"target": "hub"}, summary="Inspect hub status")]]
        else:
            target = self._status_target(text)
            if target:
                action_groups = [[AdminAction(kind="inspect_status", params={"target": target}, summary=f"Inspect {target}")]]

        if not action_groups:
            return None
        return OperatorGoalPlan(
            goal_type="read_only_lookup",
            intent="read_only_lookup",
            goal_summary="Read-only admin lookup",
            steps=[OperatorPlanStep(step_id="lookup", summary="Run admin lookup", status="ready", actions=action_groups[0])],
            action_groups=action_groups,
        )

    def _execute_goal_plan(self, plan: OperatorGoalPlan, session_key: str) -> str:
        if plan.missing_essentials:
            blocker_key = plan.missing_essentials[0]
            self._sessions[session_key] = PendingAdminRequest(
                session_type="operator_follow_up",
                state=OperatorFollowUpState(
                    goal_type=plan.goal_type,
                    original_text=str(plan.chosen_defaults.get("source_request") or plan.goal_summary),
                    current_stage="conversation",
                    unresolved_questions=[],
                    inferred_defaults=dict(plan.chosen_defaults),
                    drafted_action_groups=plan.action_groups,
                    user_response_prefix=plan.user_response,
                ),
                blocker_key=blocker_key,
            )
            return plan.user_response or self._question_for_missing_essential(plan.goal_type, blocker_key, self._sessions[session_key].state)

        if plan.reply_only and not plan.action_groups:
            return plan.user_response or self._fallback_reply("")

        parts: list[str] = []
        if plan.user_response:
            parts.append(plan.user_response)
        for action_group in plan.action_groups:
            result = self.executor.execute(action_group)
            rendered = self._render_execution_result(result)
            if rendered:
                parts.append(rendered)
            skill_prompt = self._maybe_begin_skill_approval_session(session_key, result)
            if skill_prompt:
                parts.append(skill_prompt)
            if result.status != "completed":
                break
        return "\n\n".join(part for part in parts if part) or self._fallback_reply("")

    def _resume_operator_goal(self, state: OperatorFollowUpState) -> OperatorGoalPlan:
        if state.goal_type == "set_up_scheduled_reminders":
            worker_id = state.inferred_defaults.get("worker_id", "")
            schedule = state.accumulated_answers.get("schedule", "").strip()
            destination = state.accumulated_answers.get("destination", "").strip()
            if not schedule:
                return OperatorGoalPlan(
                    goal_type="set_up_scheduled_reminders",
                    intent="approval_gated_change",
                    goal_summary=state.original_text,
                    user_response=self._question_for_missing_essential("set_up_scheduled_reminders", "schedule", state),
                    chosen_defaults=dict(state.inferred_defaults),
                    missing_essentials=["schedule"],
                    reply_only=True,
                )
            if not destination:
                return OperatorGoalPlan(
                    goal_type="set_up_scheduled_reminders",
                    intent="approval_gated_change",
                    goal_summary=state.original_text,
                    user_response=self._question_for_missing_essential("set_up_scheduled_reminders", "destination", state),
                    chosen_defaults={**dict(state.inferred_defaults), "schedule": schedule},
                    missing_essentials=["destination"],
                    reply_only=True,
                )
            summary = f"Draft a code change to enable scheduled reminders for worker `{worker_id}` on schedule `{schedule}` targeting `{destination}`."
            actions = [[AdminAction(kind="request_code_change", params={"request_summary": summary, "worker_id": worker_id, "original_request": state.original_text}, summary=summary, requires_approval=True)]]
            return OperatorGoalPlan(
                goal_type="set_up_scheduled_reminders",
                intent="approval_gated_change",
                goal_summary=state.original_text,
                user_response=(
                    f"I checked the current runtime and there is no built-in reminder scheduler for `{worker_id}` yet. "
                    f"Runtime config alone won't cover `{schedule}` -> `{destination}`, so I'm preparing an implementation proposal."
                    f"{self._implementation_targets_text()}"
                ),
                chosen_defaults={"worker_id": worker_id, "schedule": schedule, "destination": destination},
                steps=[OperatorPlanStep(step_id="proposal", summary="Prepare reminder implementation proposal", status="ready", actions=actions[0])],
                action_groups=actions,
                requires_approval=True,
            )

        if state.goal_type in {"create_tool", "create_worker", "attach_managed_bot"}:
            if state.goal_type == "create_tool":
                draft = self._seed_tool_draft(state.original_text)
                draft.update(state.inferred_defaults)
                draft.update(state.accumulated_answers)
                if draft.get("name") and not draft.get("tool_id"):
                    draft["tool_id"] = self._slugify(draft["name"])
                missing = self._missing_fields_for("create_tool", draft)
                return self._single_step_goal("create_tool", "single_step_mutation", state.original_text, "I checked the runtime catalog and I can create that tool.", draft, missing, source_request=state.original_text)

            draft = self._seed_worker_draft(state.original_text)
            draft.update(state.inferred_defaults)
            draft.update(state.accumulated_answers)
            kind = "attach_managed_bot" if state.goal_type == "attach_managed_bot" else "create_worker"
            missing = self._missing_fields_for(kind, draft)
            response = self._create_worker_intro(draft, state.original_text.lower()) if kind == "create_worker" else f"I checked the worker setup and I can attach the managed bot for `{draft.get('worker_id', 'that worker')}`."
            return self._single_step_goal(state.goal_type, "single_step_mutation", state.original_text, response, draft, missing, source_request=state.original_text)

        if state.goal_type == "improve_worker_configuration":
            worker_id = state.inferred_defaults.get("worker_id", "")
            target = state.accumulated_answers.get("improvement_target", "").strip()
            if not target:
                return OperatorGoalPlan(
                    goal_type="improve_worker_configuration",
                    intent="multi_step_operator_task",
                    goal_summary=state.original_text,
                    user_response=self._question_for_missing_essential("improve_worker_configuration", "improvement_target", state),
                    chosen_defaults=dict(state.inferred_defaults),
                    missing_essentials=["improvement_target"],
                    reply_only=True,
                )
            summary = f"Prepare a code change proposal to improve `{worker_id}` for `{target}`."
            actions = [[AdminAction(kind="request_code_change", params={"request_summary": summary, "worker_id": worker_id, "original_request": state.original_text}, summary=summary, requires_approval=True)]]
            return OperatorGoalPlan(
                goal_type="prepare_code_change_request",
                intent="approval_gated_change",
                goal_summary=summary,
                user_response=(
                    f"I checked `{worker_id}` and the current runtime doesn't have a direct config-only path for `{target}`. "
                    f"I'm preparing an implementation proposal next."
                    f"{self._implementation_targets_text()}"
                ),
                steps=[OperatorPlanStep(step_id="proposal", summary="Prepare improvement proposal", status="ready", actions=actions[0])],
                action_groups=actions,
                requires_approval=True,
            )

        if state.goal_type == "prepare_code_change_request":
            model_name = state.accumulated_answers.get("model_name", "").strip()
            if not model_name:
                return OperatorGoalPlan(
                    goal_type="prepare_code_change_request",
                    intent="approval_gated_change",
                    goal_summary=state.original_text,
                    user_response="What model should this worker use?",
                    chosen_defaults=dict(state.inferred_defaults),
                    missing_essentials=["model_name"],
                    reply_only=True,
                )
            worker_id = state.inferred_defaults.get("worker_id", "new_worker")
            worker_name = state.inferred_defaults.get("worker_name", worker_id)
            summary = f"Prepare a code change to create or upgrade worker `{worker_id}` (`{worker_name}`) using model `{model_name}` for request: {state.original_text}"
            actions = [[AdminAction(kind="request_code_change", params={"request_summary": summary, "worker_id": worker_id, "model_name": model_name, "original_request": state.original_text}, summary=summary, requires_approval=True)]]
            return OperatorGoalPlan(
                goal_type="prepare_code_change_request",
                intent="approval_gated_change",
                goal_summary=summary,
                user_response=(
                    f"I checked the current runtime and this needs executable behavior, not just catalog edits. "
                    f"I'm preparing the implementation proposal using model `{model_name}`."
                    f"{self._implementation_targets_text()}"
                ),
                steps=[OperatorPlanStep(step_id="request_code_change", summary="Prepare code-change request", status="ready", actions=actions[0])],
                action_groups=actions,
                requires_approval=True,
            )

        return OperatorGoalPlan(goal_type="generic_admin_help", intent="read_only_lookup", goal_summary="General admin help", user_response=self._fallback_reply(state.original_text), reply_only=True)

    def _single_step_goal(
        self,
        goal_type: Literal["create_worker", "create_tool", "attach_managed_bot"],
        intent: Literal["single_step_mutation"],
        goal_summary: str,
        user_response: str,
        draft: dict[str, Any],
        missing: list[str],
        *,
        source_request: str | None = None,
    ) -> OperatorGoalPlan:
        if missing:
            state = OperatorFollowUpState(
                goal_type=goal_type,
                original_text=source_request or goal_summary,
                current_stage="collect_essentials",
                inferred_defaults={k: str(v) for k, v in draft.items() if v not in (None, "") and isinstance(v, (str, int, float, bool))},
            )
            next_missing = missing[0]
            return OperatorGoalPlan(
                goal_type=goal_type,
                intent=intent,
                goal_summary=goal_summary,
                user_response=self._question_for_missing_essential(goal_type, next_missing, state),
                chosen_defaults={**dict(state.inferred_defaults), "source_request": source_request or goal_summary},
                missing_essentials=[next_missing],
                reply_only=True,
            )
        action_kind: AdminActionKind = "create_tool" if goal_type == "create_tool" else "attach_managed_bot" if goal_type == "attach_managed_bot" else "create_worker"
        params = self._action_params_for(action_kind, draft)
        actions = [[AdminAction(kind=action_kind, params=params, summary=goal_summary)]]
        return OperatorGoalPlan(
            goal_type=goal_type,
            intent=intent,
            goal_summary=goal_summary,
            user_response=user_response,
            chosen_defaults={
                **{k: str(v) for k, v in draft.items() if v not in (None, "") and isinstance(v, (str, int, float, bool))},
                **({"source_request": source_request} if source_request else {}),
            },
            steps=[OperatorPlanStep(step_id=action_kind, summary=goal_summary, status="ready", actions=actions[0])],
            action_groups=actions,
        )

    def _plan_start_or_stop_bot(self, text: str) -> OperatorGoalPlan | None:
        lowered = text.lower()
        worker_id = self._match_worker_id(text)
        if worker_id is None or "bot" not in lowered:
            return None
        if "start" not in lowered and "stop" not in lowered:
            return None
        kind: AdminActionKind = "start_bot" if "start" in lowered else "stop_bot"
        actions = [[AdminAction(kind=kind, params={"worker_id": worker_id}, summary=f"{kind} for {worker_id}")]]
        response = f"I checked `{worker_id}` and I can {kind.replace('_', ' ')} now."
        return OperatorGoalPlan(
            goal_type="configure_group_access",
            intent="single_step_mutation",
            goal_summary=f"{kind} for {worker_id}",
            user_response=response,
            steps=[OperatorPlanStep(step_id=kind, summary=f"Run {kind}", status="ready", actions=actions[0])],
            action_groups=actions,
        )

    def _plan_worker_capability_request(self, text: str) -> OperatorGoalPlan | None:
        lowered = text.lower()
        if not any(word in lowered for word in CREATE_WORDS):
            return None
        if not any(word in lowered for word in {"agent", "worker"}):
            return None
        if not any(word in lowered for word in {"image", "images", "capability", "ability", "on command", "model"}):
            return None

        draft = self._seed_worker_draft(text)
        model_name = self._extract_model_name(text)
        if not model_name:
            return OperatorGoalPlan(
                goal_type="prepare_code_change_request",
                intent="approval_gated_change",
                goal_summary=text,
                user_response="I checked the request and this needs executable behavior, so I need one decision first. What model should this worker use?",
                chosen_defaults={"worker_id": draft.get("worker_id", ""), "worker_name": draft.get("name", ""), "source_request": text},
                missing_essentials=["model_name"],
                reply_only=True,
            )

        summary = (
            f"Prepare a code change to create worker `{draft.get('worker_id', 'new_worker')}` "
            f"named `{draft.get('name', 'New Worker')}` with model `{model_name}` for request: {text}"
        )
        actions = [[AdminAction(kind="request_code_change", params={"request_summary": summary, "model_name": model_name, "worker_id": draft.get("worker_id"), "original_request": text}, summary=summary, requires_approval=True)]]
        return OperatorGoalPlan(
            goal_type="prepare_code_change_request",
            intent="approval_gated_change",
            goal_summary=summary,
            user_response=(
                f"I checked the current catalog and this worker capability needs new executable behavior. "
                f"I'm preparing a code-change proposal for model `{model_name}`."
                f"{self._implementation_targets_text()}"
            ),
            steps=[OperatorPlanStep(step_id="request_code_change", summary="Prepare code-change request", status="ready", actions=actions[0])],
            action_groups=actions,
            requires_approval=True,
        )

    def _plan_tool_access(self, text: str) -> OperatorGoalPlan | None:
        worker_id = self._match_worker_id(text)
        if worker_id is None:
            return None
        if not self._looks_like_tool_grant_request(text.lower()):
            return None

        requested_tool = self._extract_requested_tool_label(text)
        if not requested_tool:
            return OperatorGoalPlan(
                goal_type="enable_worker_capability",
                intent="single_step_mutation",
                goal_summary=f"Enable a capability for {worker_id}",
                user_response=f"I checked `{worker_id}` and I can extend them. What capability or tool should I add?",
                chosen_defaults={"worker_id": worker_id, "source_request": text},
                missing_essentials=["capability_name"],
                reply_only=True,
            )

        detail_level = self._detail_level(text)
        worker = self.hub.worker_registry.get_worker(worker_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        tool_id = self._match_tool_id(requested_tool)
        if tool_id is not None:
            actions = [[AdminAction(kind="grant_tool_access", params={"worker_id": worker_id, "tool_id": tool_id}, summary=f"Grant {worker_id} access to {tool_id}")]]
            response = self._grant_tool_intro(worker_id, loadout.loadout_id, tool_id, detail_level)
            return OperatorGoalPlan(
                goal_type="enable_worker_capability",
                intent="single_step_mutation",
                goal_summary=f"Grant {worker_id} access to {tool_id}",
                user_response=response,
                steps=[OperatorPlanStep(step_id="grant_tool_access", summary="Grant existing tool access", status="ready", actions=actions[0])],
                action_groups=actions,
            )

        summary = f"Enable `{worker_id}` to use `{requested_tool}`. This likely needs a new tool or hard-coded model integration."
        actions = [[AdminAction(kind="request_code_change", params={"request_summary": summary, "worker_id": worker_id, "requested_capability": requested_tool, "original_request": text}, summary=summary, requires_approval=True)]]
        response = self._approval_needed_intro(worker_id, loadout.loadout_id, requested_tool, detail_level)
        return OperatorGoalPlan(
            goal_type="prepare_code_change_request",
            intent="approval_gated_change",
            goal_summary=summary,
            user_response=response,
            steps=[OperatorPlanStep(step_id="request_code_change", summary="Prepare code-change request", status="ready", actions=actions[0])],
            action_groups=actions,
            requires_approval=True,
        )

    def _reminder_goal_plan(self, text: str) -> OperatorGoalPlan:
        worker_id = self._match_worker_id(text) or "aria"
        schedule = self._extract_schedule(text)
        destination = self._extract_destination(text)
        if not schedule:
            return OperatorGoalPlan(
                goal_type="set_up_scheduled_reminders",
                intent="approval_gated_change",
                goal_summary=text,
                user_response=f"I checked `{worker_id}` and there is no built-in reminder scheduler yet for scheduled reminders. What schedule should I target?",
                chosen_defaults={"worker_id": worker_id, "source_request": text},
                missing_essentials=["schedule"],
                reply_only=True,
            )
        if not destination:
            return OperatorGoalPlan(
                goal_type="set_up_scheduled_reminders",
                intent="approval_gated_change",
                goal_summary=text,
                user_response=f"I have the schedule for `{worker_id}`. Where should those reminders go?",
                chosen_defaults={"worker_id": worker_id, "schedule": schedule, "source_request": text},
                missing_essentials=["destination"],
                reply_only=True,
            )
        return self._resume_operator_goal(
            OperatorFollowUpState(
                goal_type="set_up_scheduled_reminders",
                original_text=text,
                current_stage="proposal",
                inferred_defaults={"worker_id": worker_id},
                accumulated_answers={"schedule": schedule, "destination": destination},
            )
        )

    def _low_level_tool_plan(self, text: str) -> OperatorGoalPlan:
        draft = self._seed_tool_draft(text)
        missing = self._missing_fields_for("create_tool", draft)
        return self._single_step_goal("create_tool", "single_step_mutation", text, "I checked the runtime catalog and I can create that tool.", draft, missing, source_request=text)

    def _seed_tool_draft(self, text: str) -> dict[str, Any]:
        name = self._extract_name(text)
        implementation_ref = self._extract_implementation_ref(text)
        return {
            "name": name,
            "tool_id": self._slugify(name) if name else None,
            "description": f"Runtime tool created from request: {text}",
            "implementation_ref": implementation_ref,
            "capability_tags": self._extract_capability_tags(text),
            "safety_level": self._extract_safety_level(text),
        }

    def _seed_worker_draft(self, text: str) -> dict[str, Any]:
        name = self._extract_name(text)
        worker_id = self._slugify(name) if name else self._match_worker_id(text)
        interface_mode = self._infer_interface_mode(text)
        role_id = self._infer_role(text)
        return {
            "worker_id": worker_id,
            "name": name or worker_id,
            "type_id": "agent_worker",
            "role_id": role_id,
            "loadout_id": self._default_loadout_for_role(role_id),
            "interface_mode": interface_mode,
            "enabled": True,
            "tags": self._extract_capability_tags(text),
            "bot_token": self._extract_bot_token(text),
            "smoke_test": True,
        }

    def _missing_fields_for(self, kind: Literal["create_worker", "create_tool", "attach_managed_bot"], draft: dict[str, Any]) -> list[str]:
        if kind == "create_worker":
            missing = ["name"] if not draft.get("name") else []
            if draft.get("interface_mode") == "managed" and not draft.get("bot_token"):
                missing.append("bot_token")
            return missing
        if kind == "create_tool":
            return [field for field in ("name", "implementation_ref") if not draft.get(field)]
        return [field for field in ("worker_id", "bot_token") if not draft.get(field)]

    def _action_params_for(self, kind: Literal["create_worker", "create_tool", "attach_managed_bot"], draft: dict[str, Any]) -> dict[str, Any]:
        if kind == "create_tool":
            return {
                "tool_id": draft["tool_id"],
                "name": draft["name"],
                "description": draft["description"],
                "implementation_ref": draft["implementation_ref"],
                "capability_tags": draft.get("capability_tags", []),
                "safety_level": draft.get("safety_level", "low"),
                "enabled": True,
            }
        if kind == "attach_managed_bot":
            return {"worker_id": draft["worker_id"], "bot_token": draft["bot_token"]}
        return {
            "worker_id": draft["worker_id"],
            "name": draft["name"],
            "type_id": draft.get("type_id", "default_worker"),
            "role_id": draft.get("role_id", "generalist"),
            "loadout_id": draft.get("loadout_id", "operator_core"),
            "interface_mode": draft.get("interface_mode", "internal"),
            "enabled": bool(draft.get("enabled", True)),
            "tags": list(draft.get("tags", [])),
            "smoke_test": bool(draft.get("smoke_test", True)),
            **({"bot_token": draft["bot_token"]} if draft.get("bot_token") else {}),
        }

    def _session_key(self, payload: dict[str, Any]) -> str:
        source = str(payload.get("source", "unknown"))
        chat_id = payload.get("chat_id", "unknown")
        user_id = payload.get("user_id", "unknown")
        return f"{source}:{chat_id}:{user_id}"

    def _render_execution_result(self, result: AdminExecutionResult) -> str:
        parts = [result.summary.strip()]
        validation_lines: list[str] = []
        for action_result in result.action_results:
            validation_lines.extend(action_result.validation_results)
        if validation_lines:
            parts.extend(validation_lines)
        return "\n".join(part for part in parts if part)

    def _maybe_begin_skill_approval_session(self, session_key: str, result: AdminExecutionResult) -> str | None:
        if not result.action_results:
            return None
        for action_result in result.action_results:
            if action_result.kind != "propose_skill" or not action_result.changed_ids:
                continue
            skill_id = action_result.changed_ids[0]
            proposal = self.hub.skill_library.get_pending_proposal(skill_id)
            if proposal is None:
                continue
            self._sessions[session_key] = PendingAdminRequest(session_type="skill_approval", skill_id=skill_id, target_loadout_ids=list(proposal.target_loadout_ids))
            return f"Approve this skill?\n{proposal.approval_summary}"
        return None

    def _question_for_missing_essential(self, goal_type: str, field_name: str, state: OperatorFollowUpState | None) -> str:
        if goal_type == "set_up_scheduled_reminders":
            if field_name == "schedule":
                return "What schedule should I target for those reminders?"
            if field_name == "destination":
                return "Where should those reminders go?"
        if goal_type == "create_tool":
            if field_name == "name":
                return "What should I call the tool?"
            if field_name == "implementation_ref":
                tool_name = ""
                if state is not None:
                    tool_name = state.accumulated_answers.get("name") or state.inferred_defaults.get("name", "")
                if tool_name:
                    return f"What implementation reference should I use for `{self._title_case_fragment(tool_name)}`?"
                return "What implementation reference should I use for that tool?"
        if goal_type == "create_worker":
            if field_name == "name":
                return "What should I call the worker?"
            if field_name == "bot_token":
                return "What Telegram bot token should I use?"
        if goal_type == "attach_managed_bot":
            if field_name == "worker_id":
                return "Which worker should I attach the Telegram bot to?"
            if field_name == "bot_token":
                return "What Telegram bot token should I use?"
        if goal_type == "improve_worker_configuration" and field_name == "improvement_target":
            worker_id = state.inferred_defaults.get("worker_id", "that worker") if state is not None else "that worker"
            return f"What outcome do you want most for `{worker_id}`?"
        if field_name == "capability_name":
            return "What capability or tool should I add?"
        return "What detail should I use to continue?"

    def _fallback_reply(self, text: str) -> str:
        if text.strip():
            return (
                "Tell me what you want to inspect or change in the hub. "
                "I can investigate worker setup, tool access, runtime state, skills, and operational changes, then take the next step."
            )
        return "Tell me what you want to inspect or change in the hub, and I'll handle the operator path."

    def _packs_for_text(self, text: str) -> list[str]:
        lowered = text.lower()
        packs = ["default"]
        if any(word in lowered for word in {"code", "repo", "implement", "model", "integration"}):
            packs.append("repo")
        if any(word in lowered for word in {"research", "search", "web"}):
            packs.append("web")
        if any(word in lowered for word in {"workflow", "operator", "admin"}):
            packs.append("operator")
        return packs

    def _manifest_prompt(self, packs: list[str]) -> str:
        lines = ["Available capability outcomes:"]
        for item in self.get_capability_manifest(packs):
            lines.append(f"- {item.capability_id}: {item.summary}")
        return "\n".join(lines)

    def _is_explicit_low_level_create_tool(self, lowered: str) -> bool:
        return lowered == "create tool" or lowered.startswith("create a tool") or lowered.startswith("create new tool") or lowered.startswith("create a new tool")

    def _is_create_tool_request(self, lowered: str) -> bool:
        return self._is_explicit_low_level_create_tool(lowered) or ("tool" in lowered and any(word in lowered for word in CREATE_WORDS))

    def _is_explicit_skill_request(self, text: str) -> bool:
        lowered = text.lower()
        return "create a skill" in lowered or "make a skill" in lowered or "teach a skill" in lowered

    def _looks_like_scheduled_reminder_request(self, lowered: str) -> bool:
        return "reminder" in lowered and any(word in lowered for word in {"schedule", "scheduled", "daily", "weekly", "every"})

    def _is_create_worker_request(self, lowered: str) -> bool:
        return ("worker" in lowered or "bot" in lowered) and any(word in lowered for word in CREATE_WORDS)

    def _extract_name(self, text: str) -> str | None:
        patterns = [
            r"named\s+([a-z0-9 _-]+)",
            r"call\s+(?:it|them|the worker|the tool)\s+([a-z0-9 _-]+)",
            r"tool named\s+([a-z0-9 _-]+)",
            r"worker named\s+([a-z0-9 _-]+)",
        ]
        lowered = text.lower()
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                return self._title_case_fragment(match.group(1))
        cleaned = text.strip()
        if cleaned and cleaned.lower() not in {"create tool", "create worker"} and len(cleaned.split()) <= 4 and not any(token in cleaned for token in {":", "/", "."}):
            return self._title_case_fragment(cleaned)
        return None

    def _title_case_fragment(self, value: str) -> str:
        cleaned = value.replace("_", " ").replace("-", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .!?`'\"")
        return " ".join(part.capitalize() for part in cleaned.split()) if cleaned else cleaned

    def _match_worker_id(self, text: str) -> str | None:
        lowered = text.lower()
        for worker in self.hub.worker_registry.list_workers():
            if worker.worker_id.lower() in lowered or worker.name.lower() in lowered:
                return worker.worker_id
        return None

    def _match_tool_id(self, text: str) -> str | None:
        lowered = self._slugify(text)
        for tool in self.hub.tool_registry.list_all():
            if tool.tool_id == lowered or tool.tool_id in text.lower() or tool.name.lower() in text.lower():
                return tool.tool_id
        return None

    def _infer_interface_mode(self, text: str) -> str:
        lowered = text.lower()
        if "managed" in lowered or "telegram bot" in lowered:
            return "managed"
        return "internal"

    def _infer_role(self, text: str) -> str:
        lowered = text.lower()
        if "research" in lowered:
            return "researcher"
        if any(word in lowered for word in {"operator", "admin"}):
            return "operator"
        if any(word in lowered for word in {"band", "music", "reminder", "follow-up", "follow up"}):
            return "band_assistant"
        return "operator"

    def _default_loadout_for_role(self, role_id: str) -> str:
        if role_id == "operator":
            return "operator_core"
        for loadout in self.hub.worker_registry.list_loadouts():
            if loadout.loadout_id == "operator_core":
                return loadout.loadout_id
        loadouts = self.hub.worker_registry.list_loadouts()
        return loadouts[0].loadout_id if loadouts else "operator_core"

    def _extract_implementation_ref(self, text: str) -> str | None:
        stripped = text.strip()
        if "." in stripped and " " not in stripped and "/" not in stripped:
            return stripped
        match = re.search(r"(agentic_hub\.[A-Za-z0-9_.]+)", stripped)
        if match:
            return match.group(1)
        return None

    def _extract_bot_token(self, text: str) -> str | None:
        match = TOKEN_PATTERN.search(text)
        return match.group(0) if match else None

    def _extract_capability_tags(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        ignored = {"create", "make", "tool", "worker", "named", "new", "a", "the", "and"}
        tags = [token for token in tokens if token not in ignored]
        return list(dict.fromkeys(tags[:5]))

    def _extract_safety_level(self, text: str) -> str:
        lowered = text.lower()
        if "high risk" in lowered or "danger" in lowered:
            return "high"
        if "moderate" in lowered or "medium" in lowered:
            return "medium"
        return "low"

    def _extract_requested_tool_label(self, text: str) -> str | None:
        lowered = text.lower().replace("'s", " ")
        patterns = [
            r"give\s+[a-z0-9 _-]+\s+access to\s+([a-z0-9 _.\-]+)",
            r"grant\s+[a-z0-9 _-]+\s+access to\s+([a-z0-9 _.\-]+)",
            r"allow\s+[a-z0-9 _-]+\s+to use\s+([a-z0-9 _.\-]+)",
            r"let\s+[a-z0-9 _-]+\s+use\s+([a-z0-9 _.\-]+)",
            r"enable\s+([a-z0-9 _.\-]+)\s+for\s+[a-z0-9 _-]+",
            r"give\s+[a-z0-9 _-]+\s+the ability to access\s+([a-z0-9 _.\-]+)",
            r"give\s+[a-z0-9 _-]+\s+the ability to use\s+([a-z0-9 _.\-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                label = re.sub(r"\s+", " ", match.group(1)).strip(" .!?")
                label = re.sub(r"\bmodel\b$", "", label).strip()
                if "nano-banana" in label:
                    return "google nano-banana"
                return label
        if "nano-banana" in lowered:
            return "google nano-banana"
        return None

    def _extract_model_name(self, text: str) -> str | None:
        lowered = text.lower().replace("'s", " ")
        if "nano-banana" in lowered:
            return "nano-banana"
        match = re.search(r"(?:model|use)\s+([a-z0-9 _.-]+)", lowered)
        if match:
            return match.group(1).strip(" .!?")
        return None

    def _extract_schedule(self, text: str) -> str | None:
        lowered = text.lower()
        match = re.search(r"(every [a-z0-9: ]+|daily|weekly|monthly)", lowered)
        return match.group(1).strip() if match else None

    def _extract_destination(self, text: str) -> str | None:
        lowered = text.lower()
        match = re.search(r"(?:to|into|in)\s+([#@a-z0-9 _-]+)$", lowered)
        return match.group(1).strip() if match else None

    def _extract_capability_query(self, text: str, worker_id: str) -> str | None:
        lowered = text.lower().strip()
        patterns = [
            rf"can\s+{re.escape(worker_id.lower())}\s+(.+)",
            rf"could\s+{re.escape(worker_id.lower())}\s+(.+)",
            rf"is\s+{re.escape(worker_id.lower())}\s+able to\s+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, lowered)
            if match:
                return match.group(1).strip(" ?.")
        return None

    def _slugify(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return normalized or None

    def _looks_like_repeated_skill_gap(self, text: str) -> bool:
        lowered = text.lower()
        return any(phrase in lowered for phrase in {"playbook", "consistent", "repeatable", "standard process", "triage"})

    def _overview_actions(self, lowered: str) -> list[AdminAction] | None:
        if all(word in lowered for word in {"hub", "workers", "tasks"}) and "services" in lowered:
            return [
                AdminAction(kind="inspect_status", params={"target": "hub"}, summary="Inspect hub status"),
                AdminAction(kind="list_objects", params={"kind": "workers"}, summary="List workers"),
                AdminAction(kind="list_objects", params={"kind": "tasks"}, summary="List tasks"),
                AdminAction(kind="list_services", params={}, summary="List services"),
            ]
        return None

    def _is_worker_listing_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"list workers", "show workers", "what are the workers", "which workers", "workers do we have"})

    def _is_task_listing_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"list tasks", "show tasks", "what are the tasks", "which tasks"})

    def _is_service_listing_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"list services", "show services", "what services"})

    def _is_skill_listing_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"list skills", "show skills", "what skills"})

    def _is_skill_review_request(self, lowered: str) -> bool:
        return "review skills" in lowered or "skill review" in lowered

    def _is_hub_status_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"hub status", "status of the hub", "what is the status of the hub", "what is the status of hub", "show hub status"})

    def _status_target(self, text: str) -> str | None:
        lowered = text.lower()
        if any(phrase in lowered for phrase in {"status of", "inspect", "show status for", "worker status"}):
            for worker in self.hub.worker_registry.list_workers():
                if worker.worker_id.lower() in lowered or worker.name.lower() in lowered:
                    return worker.worker_id
            for service_name in self.hub.service_manager._services:
                if service_name.lower() in lowered:
                    return service_name
        return None

    def _is_cancel_intent(self, text: str) -> bool:
        lowered = text.lower().strip()
        return lowered in CANCEL_WORDS

    def _looks_like_topic_switch(self, text: str, session: PendingAdminRequest) -> bool:
        lowered = text.lower().strip()
        if not lowered:
            return False
        if session.session_type == "skill_approval":
            if lowered in {"approve", "approved", "yes", "y", "reject", "rejected", "no", "n"}:
                return False
            return self._looks_like_new_request(lowered)
        return self._looks_like_new_request(lowered)

    def _looks_like_new_request(self, lowered: str) -> bool:
        first = lowered.split(maxsplit=1)[0]
        return lowered.startswith("/") or first in NEW_REQUEST_PREFIXES or "?" in lowered

    def _looks_like_follow_up_answer(self, lowered: str, field_name: str) -> bool:
        if field_name == "schedule":
            return bool(re.search(r"\b(every|daily|weekly|monthly|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{1,2}(?::\d{2})?(am|pm)?)\b", lowered))
        if field_name == "destination":
            return lowered.startswith(("to ", "in ", "into ", "#", "@")) or "group" in lowered or "chat" in lowered
        if field_name == "model_name":
            return len(lowered.split()) <= 5 and not self._looks_like_new_request(lowered)
        if field_name == "bot_token":
            return bool(TOKEN_PATTERN.search(lowered))
        if field_name in {"name", "capability_name", "improvement_target"}:
            return not self._looks_like_new_request(lowered)
        return False

    def _merge_follow_up(self, original_request: str, answer: str, blocker_key: str | None) -> str:
        cleaned = answer.strip()
        if not blocker_key:
            return f"{original_request}\nAdditional context: {cleaned}"
        if blocker_key == "name":
            return f"{original_request} named {cleaned}"
        if blocker_key == "implementation_ref":
            return f"{original_request}\nImplementation reference: {cleaned}"
        if blocker_key == "bot_token":
            return f"{original_request}\nTelegram bot token: {cleaned}"
        if blocker_key == "model_name":
            return f"{original_request}\nUse model {cleaned}"
        if blocker_key == "schedule":
            return f"{original_request}\nSchedule: {cleaned}"
        if blocker_key == "destination":
            return f"{original_request}\nDestination: {cleaned}"
        if blocker_key == "capability_name":
            return f"{original_request}\nRequested capability: {cleaned}"
        if blocker_key == "improvement_target":
            return f"{original_request}\nDesired outcome: {cleaned}"
        return f"{original_request}\nAdditional context: {cleaned}"

    def _prepend_fresh_start(self, text: str) -> str:
        return f"Cancelled the previous flow and started fresh.\n\n{text}"

    def _detail_level(self, text: str) -> str:
        lowered = text.lower()
        if any(term in lowered for term in TECHNICAL_TERMS) or "`" in text or "/" in text or "_" in text:
            return "technical"
        return "concise"

    def _is_worker_tools_question(self, lowered: str) -> bool:
        return (
            "tool" in lowered
            and any(phrase in lowered for phrase in {"what tools", "which tools", "tools does", "tool access", "allowed tools"})
        ) or ("access to" in lowered and "what" in lowered)

    def _is_worker_context_question(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in {
                "what loadout",
                "which loadout",
                "what role",
                "how is",
                "configured",
                "set up",
                "what prompts",
                "what skills",
            }
        )

    def _is_delegation_question(self, lowered: str) -> bool:
        return ("vanta" in lowered or "you" in lowered) and any(word in lowered for word in {"delegate", "delegation", "call", "lean on", "use to help"})

    def _inspect_worker_capability_plan(self, text: str) -> OperatorGoalPlan | None:
        worker_id = self._match_worker_id(text)
        if worker_id is None:
            return None
        lowered = text.lower()
        if not any(prefix in lowered for prefix in {f"can {worker_id}", f"could {worker_id}", f"is {worker_id} able to"}):
            return None

        query = self._extract_capability_query(text, worker_id)
        if not query:
            return None
        response = self._analyze_worker_capability(worker_id, query, self._detail_level(text))
        return OperatorGoalPlan(
            goal_type="read_only_lookup",
            intent="read_only_lookup",
            goal_summary=f"Inspect capability for {worker_id}",
            user_response=response,
            reply_only=True,
        )

    def _analyze_worker_capability(self, worker_id: str, query: str, detail_level: str) -> str:
        worker = self.hub.worker_registry.get_worker(worker_id)
        role = self.hub.worker_registry.get_role(worker.role_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        normalized_query = self._slugify(query) or ""
        query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))

        current_tool_ids = list(loadout.allowed_tool_ids)
        current_markers = set(current_tool_ids)
        current_markers.update(re.findall(r"[a-z0-9]+", role.purpose.lower()))
        current_markers.update(self._path_tokens(loadout.prompt_refs))
        current_markers.update(self._path_tokens(loadout.skill_refs))
        current_markers.update(tag.lower() for tag in getattr(worker, "tags", []))

        if normalized_query and any(normalized_query in marker or marker in normalized_query for marker in current_markers if marker):
            return self._capability_response(worker_id, loadout.loadout_id, query, "already_supported", detail_level)
        if query_tokens and query_tokens.intersection(current_markers):
            return self._capability_response(worker_id, loadout.loadout_id, query, "already_supported", detail_level)

        matching_runtime_tool = None
        for tool in self.hub.tool_registry.list_all():
            tool_markers = {tool.tool_id.lower(), tool.name.lower(), *(tag.lower() for tag in tool.capability_tags)}
            if normalized_query and any(normalized_query in marker or marker in normalized_query for marker in tool_markers):
                matching_runtime_tool = tool.tool_id
                break
            if query_tokens and query_tokens.intersection(set(re.findall(r"[a-z0-9]+", " ".join(tool_markers)))):
                matching_runtime_tool = tool.tool_id
                break

        if matching_runtime_tool:
            if matching_runtime_tool in current_tool_ids:
                return self._capability_response(worker_id, loadout.loadout_id, query, "already_supported", detail_level, tool_id=matching_runtime_tool)
            return self._capability_response(worker_id, loadout.loadout_id, query, "runtime_configurable", detail_level, tool_id=matching_runtime_tool)

        return self._capability_response(worker_id, loadout.loadout_id, query, "code_change", detail_level)

    def _capability_response(self, worker_id: str, loadout_id: str, query: str, status: str, detail_level: str, tool_id: str | None = None) -> str:
        if status == "already_supported":
            if detail_level == "technical":
                reason = f"based on loadout `{loadout_id}` and current worker context"
                if tool_id:
                    reason = f"because `{tool_id}` is already available through `{loadout_id}`"
                return f"I checked `{worker_id}` and this looks already supported {reason}. Query: `{query}`."
            return f"I checked `{worker_id}` and this looks like something they can already handle."
        if status == "runtime_configurable":
            if detail_level == "technical":
                return f"I checked `{worker_id}`. The runtime already has `{tool_id}`, but `{loadout_id}` does not currently allow it, so this is a runtime config change rather than a code change."
            return f"I checked `{worker_id}` and this looks like a runtime config change, not a rebuild."
        if detail_level == "technical":
            return (
                f"I checked `{worker_id}`, loadout `{loadout_id}`, the current tools, prompts, and skills. "
                f"I do not see a runtime path for `{query}`, so this would need new executable behavior."
            )
        return f"I checked `{worker_id}` and I don't see a built-in runtime path for that yet."

    def _path_tokens(self, refs: list[str]) -> set[str]:
        tokens: set[str] = set()
        for ref in refs:
            name = Path(ref).stem.lower()
            tokens.update(re.findall(r"[a-z0-9]+", name))
        return tokens

    def _worker_tools_intro(self, worker_id: str, detail_level: str) -> str:
        if detail_level == "technical":
            return f"I checked `{worker_id}` and I'm inspecting the worker -> loadout -> allowed tools chain."
        return f"I checked `{worker_id}` and I'm looking at what tools they can use right now."

    def _worker_context_intro(self, worker_id: str, detail_level: str) -> str:
        if detail_level == "technical":
            return f"I checked `{worker_id}` and I'm pulling the role, loadout, prompt, and skill context."
        return f"I checked how `{worker_id}` is currently set up."

    def _grant_tool_intro(self, worker_id: str, loadout_id: str, tool_id: str, detail_level: str) -> str:
        if detail_level == "technical":
            return f"I checked `{worker_id}`. Loadout `{loadout_id}` does not currently allow `{tool_id}`, and I can update that runtime config now."
        return f"I checked `{worker_id}` and they don't have `{tool_id}` yet, but I can add it now."

    def _approval_needed_intro(self, worker_id: str, loadout_id: str, capability_name: str, detail_level: str) -> str:
        if detail_level == "technical":
            return (
                f"I checked `{worker_id}`, loadout `{loadout_id}`, and the current runtime tool registry. "
                f"I do not see a runtime tool for `{capability_name}`, so runtime config alone is not enough. "
                f"I'm preparing a code-change proposal next."
                f"{self._implementation_targets_text()}"
            )
        return (
            f"I checked `{worker_id}` and I don't see a built-in runtime path for `{capability_name}` yet, "
            f"so this needs an implementation proposal."
            f"{self._implementation_targets_text()}"
        )

    def _implementation_targets_text(self) -> str:
        worker_ids = {worker.worker_id for worker in self.hub.worker_registry.list_workers()}
        targets = [worker_id for worker_id in ("forge", "nova") if worker_id in worker_ids]
        if not targets:
            return ""
        names = " and ".join(f"`{worker_id}`" for worker_id in targets)
        return f" Best internal help targets right now: {names}."

    def _create_worker_intro(self, draft: dict[str, Any], lowered: str) -> str:
        worker_id = draft.get("worker_id", "worker")
        loadout_id = draft.get("loadout_id", "operator_core")
        interface_mode = draft.get("interface_mode", "internal")
        if self._detail_level(lowered) == "technical":
            return f"I checked the runtime catalog and there is no existing worker conflict for `{worker_id}`. I can create it with loadout `{loadout_id}` in `{interface_mode}` mode and validate it."
        return f"I checked the current setup and I can create `{worker_id}` with a sensible runtime config."

    def _looks_like_tool_grant_request(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in {
                "give ",
                "grant ",
                "allow ",
                "let ",
                "enable ",
                "can we give ",
                "can you give ",
                "i want to give ",
            }
        )

