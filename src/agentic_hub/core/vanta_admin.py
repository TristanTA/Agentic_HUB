from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from agentic_hub.core.admin_executor import AdminExecutor
from agentic_hub.models.admin_action import AdminAction, AdminExecutionResult
from agentic_hub.models.vanta_capability import VantaCapability


TOKEN_PATTERN = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]+\b")
CREATE_WORDS = {"create", "make", "new", "add", "build"}
CANCEL_WORDS = {"cancel", "stop", "never mind", "nevermind", "abort"}
NEW_REQUEST_PREFIXES = {
    "what",
    "why",
    "how",
    "where",
    "which",
    "who",
    "can",
    "could",
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
BOOTSTRAP_CONTEXT = (
    "Hub layout: workers/loadouts/tools live in content packs plus runtime overrides. "
    "Current truth comes from the live registries after catalog reload. "
    "Authored prompts, skills, docs, and worker definitions live under content/. "
    "Use registry state first, inspect repo files when registry state is not enough, "
    "mutate runtime when safe, and require approval only for executable behavior changes."
)


@dataclass(frozen=True)
class VantaSystemConfig:
    system_id: str = "vanta_system_admin"
    display_name: str = "Vanta"
    locked: bool = True
    default_packs: tuple[str, ...] = ("default",)
    escalation_packs: tuple[str, ...] = ("repo", "web", "operator")


@dataclass
class OperatorSession:
    original_request: str
    gathered_facts: list[str] = field(default_factory=list)
    recent_conclusions: list[str] = field(default_factory=list)
    last_action: str | None = None
    last_blocker: str | None = None
    worker_id: str | None = None


@dataclass
class PendingAdminRequest:
    session_type: Literal["conversation", "skill_approval"]
    conversation: OperatorSession | None = None
    skill_id: str | None = None
    target_loadout_ids: list[str] | None = None


class VantaAdminAgent:
    SYSTEM_CONFIG = VantaSystemConfig()
    _CAPABILITIES: tuple[VantaCapability, ...] = (
        VantaCapability(capability_id="inspect_hub_status", label="inspect hub status", summary="Read overall hub health and counts.", action_kind="inspect_status", access="read", required_argument_names=["target"]),
        VantaCapability(capability_id="list_workers", label="list workers", summary="Read worker inventory and interface modes.", action_kind="list_objects", access="read", required_argument_names=["kind"]),
        VantaCapability(capability_id="list_tasks", label="list tasks", summary="Read scheduled task inventory.", action_kind="list_objects", access="read", required_argument_names=["kind"]),
        VantaCapability(capability_id="list_services", label="list services", summary="Read registered services and states.", action_kind="list_services", access="read"),
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
            fresh = self._respond(message, session_key)
            return f"Cancelled the previous flow and started fresh.\n\n{fresh}"

        if pending is not None:
            return self._continue_session(session_key, message)

        return self._respond(message, session_key)

    def _continue_session(self, session_key: str, answer: str) -> str:
        pending = self._sessions[session_key]
        if pending.session_type == "skill_approval":
            skill_id = str(pending.skill_id)
            loadout_ids = list(pending.target_loadout_ids or [])
            decision = answer.strip().lower()
            del self._sessions[session_key]
            if decision in {"approve", "approved", "yes", "y"}:
                result = self.executor.execute([AdminAction(kind="approve_skill", params={"skill_id": skill_id, "loadout_ids": loadout_ids}, summary=f"Approve skill {skill_id}")])
                return self._render_execution_result(result)
            if decision in {"reject", "rejected", "no", "n"}:
                result = self.executor.execute([AdminAction(kind="reject_skill", params={"skill_id": skill_id}, summary=f"Reject skill {skill_id}")])
                return self._render_execution_result(result)
            self._sessions[session_key] = pending
            return "Please reply `approve` or `reject`, or say `cancel` to exit this approval."

        conversation = pending.conversation
        if conversation is None:
            del self._sessions[session_key]
            return self._best_effort_reply(answer)

        merged = self._merge_follow_up(conversation.original_request, answer, conversation.last_blocker)
        del self._sessions[session_key]
        updated_session = OperatorSession(
            original_request=merged,
            gathered_facts=list(conversation.gathered_facts),
            recent_conclusions=list(conversation.recent_conclusions),
            last_action=conversation.last_action,
            last_blocker=conversation.last_blocker,
            worker_id=conversation.worker_id,
        )
        return self._respond(merged, session_key, session=updated_session)

    def _respond(self, request: str, session_key: str, *, session: OperatorSession | None = None) -> str:
        session = session or OperatorSession(original_request=request, worker_id=self._match_worker_id(request))
        if self._looks_like_change_request(request):
            mutation = self._handle_change_request(request, session_key, session)
            if mutation is not None:
                return mutation
            direct = self._inspect_and_reply(request, session)
            if direct is not None:
                return direct
        else:
            direct = self._inspect_and_reply(request, session)
            if direct is not None:
                return direct
            mutation = self._handle_change_request(request, session_key, session)
            if mutation is not None:
                return mutation
        return self._best_effort_reply(request)

    def _inspect_and_reply(self, request: str, session: OperatorSession) -> str | None:
        lowered = request.lower().strip()
        detail_level = self._detail_level(request)
        worker_id = self._match_worker_id(request)

        if not lowered:
            return self._best_effort_reply(request)
        if self._is_overview_request(lowered):
            parts = [
                self._execute_actions([AdminAction(kind="inspect_status", params={"target": "hub"}, summary="Inspect hub status")]),
                self._execute_actions([AdminAction(kind="list_objects", params={"kind": "workers"}, summary="List workers")]),
                self._execute_actions([AdminAction(kind="list_objects", params={"kind": "tasks"}, summary="List tasks")]),
                self._execute_actions([AdminAction(kind="list_services", params={}, summary="List services")]),
            ]
            return "\n\n".join(parts)
        if self._is_hub_status_request(lowered):
            return self._execute_actions([AdminAction(kind="inspect_status", params={"target": "hub"}, summary="Inspect hub status")])
        if self._is_worker_listing_request(lowered):
            return self._execute_actions([AdminAction(kind="list_objects", params={"kind": "workers"}, summary="List workers")])
        if self._is_task_listing_request(lowered):
            return self._execute_actions([AdminAction(kind="list_objects", params={"kind": "tasks"}, summary="List tasks")])
        if self._is_service_listing_request(lowered):
            return self._execute_actions([AdminAction(kind="list_services", params={}, summary="List services")])
        if self._is_tool_listing_request(lowered):
            return self._tool_inventory_response(detail_level)
        if self._is_skill_listing_request(lowered):
            return self._execute_actions([AdminAction(kind="list_skills", params={}, summary="List skills")])
        if self._is_skill_review_request(lowered):
            return self._execute_actions([AdminAction(kind="review_skills", params={}, summary="Review skills")])

        target = self._status_target(request)
        if target is not None:
            return self._execute_actions([AdminAction(kind="inspect_status", params={"target": target}, summary=f"Inspect {target}")])

        if worker_id is not None and self._is_worker_tools_question(lowered):
            return self._worker_tools_response(worker_id, detail_level)
        if worker_id is not None and self._is_worker_context_question(lowered):
            return self._worker_context_response(worker_id, detail_level)
        if worker_id is not None and self._is_worker_scope_question(lowered):
            return self._worker_scope_response(worker_id, detail_level)
        if worker_id is not None and self._looks_like_capability_question(lowered, worker_id):
            query = self._extract_capability_query(request, worker_id)
            if query:
                return self._analyze_worker_capability(worker_id, query, detail_level)
        if self._is_delegation_question(lowered):
            return self._delegation_response()
        if self._looks_like_repo_location_question(lowered):
            found = self._repo_location_response(request)
            if found is not None:
                return found
        if worker_id is not None:
            return self._worker_repo_summary(worker_id, detail_level)
        if "tool" in lowered:
            return self._tool_inventory_response(detail_level)

        searched = self._search_repo_for_question(request)
        if searched is not None:
            return searched
        return None

    def _handle_change_request(self, request: str, session_key: str, session: OperatorSession) -> str | None:
        start_stop = self._handle_start_stop_bot(request)
        if start_stop is not None:
            return start_stop
        reminder = self._handle_reminder_request(request, session_key, session)
        if reminder is not None:
            return reminder
        capability_worker = self._handle_worker_capability_request(request, session_key, session)
        if capability_worker is not None:
            return capability_worker
        tool_access = self._handle_tool_access_request(request, session_key, session)
        if tool_access is not None:
            return tool_access
        attach_bot = self._handle_attach_bot_request(request, session_key, session)
        if attach_bot is not None:
            return attach_bot
        create_tool = self._handle_create_tool_request(request, session_key, session)
        if create_tool is not None:
            return create_tool
        create_worker = self._handle_create_worker_request(request, session_key, session)
        if create_worker is not None:
            return create_worker
        improve = self._handle_improvement_request(request, session_key, session)
        if improve is not None:
            return improve
        explicit_skill = self._handle_skill_request(request, session_key)
        if explicit_skill is not None:
            return explicit_skill
        return None

    def _handle_skill_request(self, request: str, session_key: str) -> str | None:
        if self._is_explicit_skill_request(request):
            target_loadout_ids = [self._seed_worker_draft(request).get("loadout_id", "operator_core")]
            result = self.executor.execute([AdminAction(kind="propose_skill", params={"request_text": request, "target_loadout_ids": target_loadout_ids, "explicit": True}, summary="Draft reusable skill proposal")])
            return self._render_with_skill_approval(session_key, result)
        if self._looks_like_repeated_skill_gap(request):
            gap_record = self.hub.skill_library.record_gap(request, explicit=False)
            if self.hub.skill_library.should_propose(gap_record, explicit=False):
                target_loadout_ids = [self._seed_worker_draft(request).get("loadout_id", "operator_core")]
                result = self.executor.execute([AdminAction(kind="propose_skill", params={"request_text": request, "target_loadout_ids": target_loadout_ids, "explicit": False}, summary="Draft reusable skill proposal from repeated demand")])
                return self._render_with_skill_approval(session_key, result)
            return "I noted that recurring need. If it keeps coming up, I'll turn it into a reusable skill proposal."
        return None

    def _handle_start_stop_bot(self, request: str) -> str | None:
        lowered = request.lower()
        worker_id = self._match_worker_id(request)
        if worker_id is None or "bot" not in lowered:
            return None
        if "start" not in lowered and "stop" not in lowered:
            return None
        kind = "start_bot" if "start" in lowered else "stop_bot"
        intro = f"I checked `{worker_id}` and I can {kind.replace('_', ' ')} now."
        result = self.executor.execute([AdminAction(kind=kind, params={"worker_id": worker_id}, summary=f"{kind} for {worker_id}")])
        return f"{intro}\n\n{self._render_execution_result(result)}"

    def _handle_reminder_request(self, request: str, session_key: str, session: OperatorSession) -> str | None:
        lowered = request.lower()
        if "create tool" in lowered or "tool named" in lowered:
            return None
        if "reminder" not in lowered or not any(word in lowered for word in {"schedule", "scheduled", "daily", "weekly", "every"}):
            return None
        worker_id = self._match_worker_id(request) or session.worker_id or "aria"
        schedule = self._extract_schedule(request)
        destination = self._extract_destination(request)
        if not schedule:
            return self._block(session_key, session, "schedule", worker_id, f"I checked `{worker_id}` and there is no built-in reminder scheduler yet for scheduled reminders. What schedule should I target?")
        if not destination:
            return self._block(session_key, session, "destination", worker_id, f"I have the schedule for `{worker_id}`. Where should those reminders go?")
        summary = f"Enable scheduled reminders for worker `{worker_id}` on schedule `{schedule}` targeting `{destination}`."
        intro = (
            f"I checked the current runtime and there is no built-in reminder scheduler for `{worker_id}` yet. "
            f"Runtime config alone will not cover `{schedule}` -> `{destination}`, so this needs an implementation proposal."
            f"{self._implementation_targets_text()}"
        )
        result = self.executor.execute([AdminAction(kind="request_code_change", params={"request_summary": summary, "worker_id": worker_id, "original_request": request}, summary=summary, requires_approval=True)])
        return f"{intro}\n\n{self._render_execution_result(result)}"

    def _handle_worker_capability_request(self, request: str, session_key: str, session: OperatorSession) -> str | None:
        lowered = request.lower()
        if not any(word in lowered for word in CREATE_WORDS):
            return None
        if not any(word in lowered for word in {"agent", "worker"}):
            return None
        if not any(word in lowered for word in {"image", "images", "capability", "ability", "on command", "model"}):
            return None
        draft = self._seed_worker_draft(request)
        model_name = self._extract_model_name(request)
        if not model_name:
            return self._block(session_key, session, "model_name", draft.get("worker_id"), "I checked the request and this needs executable behavior, so I need one decision first. What model should this worker use?")
        summary = (
            f"Prepare a code change to create worker `{draft.get('worker_id', 'new_worker')}` "
            f"named `{draft.get('name', 'New Worker')}` with model `{model_name}` for request: {request}"
        )
        intro = (
            f"I checked the current catalog and this worker capability needs new executable behavior. "
            f"I'm preparing a code-change proposal for model `{model_name}`."
            f"{self._implementation_targets_text()}"
        )
        result = self.executor.execute([AdminAction(kind="request_code_change", params={"request_summary": summary, "model_name": model_name, "worker_id": draft.get("worker_id"), "original_request": request}, summary=summary, requires_approval=True)])
        return f"{intro}\n\n{self._render_execution_result(result)}"

    def _handle_tool_access_request(self, request: str, session_key: str, session: OperatorSession) -> str | None:
        lowered = request.lower()
        worker_id = self._match_worker_id(request)
        if worker_id is None or not self._looks_like_tool_grant_request(lowered):
            return None
        requested_tool = self._extract_requested_tool_label(request)
        if not requested_tool:
            return self._block(session_key, session, "capability_name", worker_id, f"I checked `{worker_id}` and I can extend them. What capability or tool should I add?")
        detail_level = self._detail_level(request)
        worker = self.hub.worker_registry.get_worker(worker_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        tool_id = self._match_tool_id(requested_tool)
        if tool_id is not None:
            intro = self._grant_tool_intro(worker_id, loadout.loadout_id, tool_id, detail_level)
            result = self.executor.execute([AdminAction(kind="grant_tool_access", params={"worker_id": worker_id, "tool_id": tool_id}, summary=f"Grant {worker_id} access to {tool_id}")])
            return f"{intro}\n\n{self._render_execution_result(result)}"
        summary = f"Enable `{worker_id}` to use `{requested_tool}`. This likely needs a new tool or hard-coded model integration."
        intro = self._approval_needed_intro(worker_id, loadout.loadout_id, requested_tool, detail_level)
        result = self.executor.execute([AdminAction(kind="request_code_change", params={"request_summary": summary, "worker_id": worker_id, "requested_capability": requested_tool, "original_request": request}, summary=summary, requires_approval=True)])
        return f"{intro}\n\n{self._render_execution_result(result)}"

    def _handle_attach_bot_request(self, request: str, session_key: str, session: OperatorSession) -> str | None:
        lowered = request.lower()
        if "attach" not in lowered or "bot" not in lowered:
            return None
        draft = self._seed_worker_draft(request)
        if not draft.get("worker_id"):
            return self._block(session_key, session, "worker_id", None, "Which worker should I attach the Telegram bot to?")
        if not draft.get("bot_token"):
            return self._block(session_key, session, "bot_token", draft.get("worker_id"), f"I checked `{draft.get('worker_id', 'that worker')}` and I can attach the bot once I have the Telegram bot token.")
        intro = f"I checked the worker setup and I can attach the managed bot for `{draft['worker_id']}`."
        result = self.executor.execute([AdminAction(kind="attach_managed_bot", params={"worker_id": draft["worker_id"], "bot_token": draft["bot_token"]}, summary=f"Attach managed bot for {draft['worker_id']}")])
        return f"{intro}\n\n{self._render_execution_result(result)}"

    def _handle_create_tool_request(self, request: str, session_key: str, session: OperatorSession) -> str | None:
        lowered = request.lower().strip()
        if not self._is_create_tool_request(lowered):
            return None
        draft = self._seed_tool_draft(request)
        if not draft.get("name"):
            return self._block(session_key, session, "name", None, "What should I call the tool?")
        if not draft.get("implementation_ref"):
            return self._block(session_key, session, "implementation_ref", None, f"What implementation reference should I use for `{self._title_case_fragment(str(draft['name']))}`?")
        intro = "I checked the runtime catalog and I can create that tool."
        result = self.executor.execute([AdminAction(kind="create_tool", params={"tool_id": draft["tool_id"], "name": draft["name"], "description": draft["description"], "implementation_ref": draft["implementation_ref"], "capability_tags": draft.get("capability_tags", []), "safety_level": draft.get("safety_level", "low"), "enabled": True}, summary=request)])
        return f"{intro}\n\n{self._render_execution_result(result)}"

    def _handle_create_worker_request(self, request: str, session_key: str, session: OperatorSession) -> str | None:
        lowered = request.lower().strip()
        if not self._is_create_worker_request(lowered):
            return None
        draft = self._seed_worker_draft(request)
        if not draft.get("name"):
            return self._block(session_key, session, "name", draft.get("worker_id"), "What should I call the worker?")
        if draft.get("interface_mode") == "managed" and not draft.get("bot_token"):
            return self._block(session_key, session, "bot_token", draft.get("worker_id"), "What Telegram bot token should I use?")
        intro = self._create_worker_intro(draft, request)
        result = self.executor.execute([AdminAction(kind="create_worker", params={"worker_id": draft["worker_id"], "name": draft["name"], "type_id": draft["type_id"], "role_id": draft["role_id"], "loadout_id": draft["loadout_id"], "interface_mode": draft["interface_mode"], "enabled": True, "tags": list(draft.get("tags", [])), "smoke_test": bool(draft.get("smoke_test", True)), **({"bot_token": draft["bot_token"]} if draft.get("bot_token") else {})}, summary=f"Create worker {draft['worker_id']}")])
        return f"{intro}\n\n{self._render_execution_result(result)}"

    def _handle_improvement_request(self, request: str, session_key: str, session: OperatorSession) -> str | None:
        lowered = request.lower()
        worker_id = self._match_worker_id(request)
        if worker_id is None or not any(word in lowered for word in {"improve", "better", "upgrade", "refine"}):
            return None
        improvement_target = self._extract_improvement_target(request)
        if not improvement_target:
            return self._block(session_key, session, "improvement_target", worker_id, f"I checked `{worker_id}` and I can help improve it. What outcome do you want most right now?")
        summary = f"Prepare a code change proposal to improve `{worker_id}` for `{improvement_target}`."
        intro = (
            f"I checked `{worker_id}` and the current runtime does not have a direct config-only path for `{improvement_target}`. "
            f"I'm preparing an implementation proposal next."
            f"{self._implementation_targets_text()}"
        )
        result = self.executor.execute([AdminAction(kind="request_code_change", params={"request_summary": summary, "worker_id": worker_id, "original_request": request}, summary=summary, requires_approval=True)])
        return f"{intro}\n\n{self._render_execution_result(result)}"

    def _block(self, session_key: str, previous: OperatorSession, blocker: str, worker_id: str | None, reply: str) -> str:
        self._sessions[session_key] = PendingAdminRequest(
            session_type="conversation",
            conversation=OperatorSession(
                original_request=previous.original_request,
                gathered_facts=list(previous.gathered_facts),
                recent_conclusions=list(previous.recent_conclusions),
                last_action=previous.last_action,
                last_blocker=blocker,
                worker_id=worker_id or previous.worker_id,
            ),
        )
        return reply

    def _render_with_skill_approval(self, session_key: str, result: AdminExecutionResult) -> str:
        response = self._render_execution_result(result)
        if not result.action_results:
            return response
        for item in result.action_results:
            if item.kind != "propose_skill" or not item.changed_ids:
                continue
            proposal = self.hub.skill_library.get_pending_proposal(item.changed_ids[0])
            if proposal is None:
                continue
            self._sessions[session_key] = PendingAdminRequest(session_type="skill_approval", skill_id=item.changed_ids[0], target_loadout_ids=list(proposal.target_loadout_ids))
            return f"{response}\n\nApprove this skill?\n{proposal.approval_summary}"
        return response

    def _execute_actions(self, actions: list[AdminAction]) -> str:
        return self._render_execution_result(self.executor.execute(actions))

    def _render_execution_result(self, result: AdminExecutionResult) -> str:
        parts = [result.summary.strip()]
        validation_lines: list[str] = []
        for action_result in result.action_results:
            validation_lines.extend(action_result.validation_results)
        if validation_lines:
            parts.extend(validation_lines)
        return "\n".join(part for part in parts if part)

    def _best_effort_reply(self, request: str) -> str:
        searched = self._search_repo_for_question(request)
        if searched is not None:
            return searched
        tool_count = len(self.hub.tool_registry.list_all())
        worker_count = len(self.hub.worker_registry.list_workers())
        return (
            f"I checked the live hub state using Vanta's operator context. {BOOTSTRAP_CONTEXT} "
            f"Right now I can see {worker_count} workers and {tool_count} tools. "
            f"I could not tie your request to one exact object yet, but I did not stop trying to help."
        )

    def _search_repo_for_question(self, request: str) -> str | None:
        tokens = self._repo_search_tokens(request)
        if not tokens:
            return None
        matches: list[tuple[Path, int, str]] = []
        for root_name in ("src", "content", "docs"):
            root = self.hub.project_root / root_name
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in {".py", ".json", ".md"}:
                    continue
                try:
                    raw = path.read_text(encoding="utf-8")
                except Exception:
                    continue
                best_score = 0
                best_line = ""
                for line in raw.splitlines():
                    lowered = line.lower()
                    score = sum(1 for token in tokens if token in lowered)
                    if score > best_score:
                        best_score = score
                        best_line = line.strip()
                path_score = sum(1 for token in tokens if token in path.as_posix().lower())
                total = best_score + path_score
                if total > 0:
                    matches.append((path, total, best_line))
        if not matches:
            return None
        matches.sort(key=lambda item: (-item[1], len(str(item[0]))))
        rows = [f"- `{path.relative_to(self.hub.project_root).as_posix()}`: {(line or 'relevant repo file')[:120]}" for path, _, line in matches[:4]]
        return "I did not find a direct runtime-only answer, so I searched the repo and found these likely sources:\n" + "\n".join(rows)

    def _repo_location_response(self, request: str) -> str | None:
        worker_id = self._match_worker_id(request)
        lowered = request.lower()
        if worker_id is None:
            return self._search_repo_for_question(request)
        worker = self.hub.worker_registry.get_worker(worker_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        if "soul" in lowered and loadout.soul_ref:
            return f"I checked `{worker_id}` in the live catalog. Their soul file is defined at `{loadout.soul_ref}`."
        if "prompt" in lowered and loadout.prompt_refs:
            refs = ", ".join(f"`{ref}`" for ref in loadout.prompt_refs)
            return f"I checked `{worker_id}` in the live catalog. Their prompt refs are {refs}."
        if "skill" in lowered and loadout.skill_refs:
            refs = ", ".join(f"`{ref}`" for ref in loadout.skill_refs)
            return f"I checked `{worker_id}` in the live catalog. Their skill refs are {refs}."
        return self._search_repo_for_question(request)

    def _worker_tools_response(self, worker_id: str, detail_level: str) -> str:
        worker = self.hub.worker_registry.get_worker(worker_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        tool_ids = list(loadout.allowed_tool_ids)
        tools_text = ", ".join(f"`{tool_id}`" for tool_id in tool_ids) if tool_ids else "no allowed tools"
        detail = f"Worker `{worker.worker_id}` uses loadout `{loadout.loadout_id}`. Allowed tools: {tools_text}." if detail_level == "technical" else f"`{worker.worker_id}` can currently use {tools_text}."
        return f"{self._worker_tools_intro(worker_id, detail_level)}\n\n{detail}"

    def _worker_context_response(self, worker_id: str, detail_level: str) -> str:
        worker = self.hub.worker_registry.get_worker(worker_id)
        role = self.hub.worker_registry.get_role(worker.role_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        if detail_level == "technical":
            body = (
                f"Worker `{worker.worker_id}` | role=`{role.role_id}` | loadout=`{loadout.loadout_id}` | "
                f"interface=`{worker.interface_mode}` | prompts={len(loadout.prompt_refs)} | skills={len(loadout.skill_refs)} | tools={len(loadout.allowed_tool_ids)}"
            )
        else:
            body = (
                f"`{worker.worker_id}` is set up as {role.name.lower()} with {len(loadout.allowed_tool_ids)} runtime tool"
                f"{'' if len(loadout.allowed_tool_ids) == 1 else 's'}, {len(loadout.skill_refs)} skill"
                f"{'' if len(loadout.skill_refs) == 1 else 's'}, and {len(loadout.prompt_refs)} prompt file"
                f"{'' if len(loadout.prompt_refs) == 1 else 's'}."
            )
        return f"{self._worker_context_intro(worker_id, detail_level)}\n\n{body}"

    def _worker_scope_response(self, worker_id: str, detail_level: str) -> str:
        worker = self.hub.worker_registry.get_worker(worker_id)
        role = self.hub.worker_registry.get_role(worker.role_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        tool_ids = list(loadout.allowed_tool_ids)
        if detail_level == "technical":
            tools_text = ", ".join(f"`{tool_id}`" for tool_id in tool_ids) if tool_ids else "none"
            return (
                f"I checked `{worker_id}` again. Runtime-tool-wise, `{loadout.loadout_id}` only allows {tools_text}. "
                f"But `{worker_id}` also has role `{role.role_id}`, {len(loadout.skill_refs)} skill ref"
                f"{'' if len(loadout.skill_refs) == 1 else 's'}, and {len(loadout.prompt_refs)} prompt ref"
                f"{'' if len(loadout.prompt_refs) == 1 else 's'}, so Telegram is not the whole picture."
            )
        if tool_ids == ["telegram_send_message"]:
            return (
                f"`{worker_id}` only has one runtime tool right now: `telegram_send_message`. "
                f"But they still have role, prompt, and skill context beyond that, so this is not the whole picture."
            )
        return f"`{worker_id}` has {len(tool_ids)} runtime tool{'s' if len(tool_ids) != 1 else ''} right now, plus role, prompt, and skill context."

    def _worker_repo_summary(self, worker_id: str, detail_level: str) -> str:
        worker = self.hub.worker_registry.get_worker(worker_id)
        role = self.hub.worker_registry.get_role(worker.role_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        tool_ids = list(loadout.allowed_tool_ids)
        tools_text = ", ".join(f"`{tool_id}`" for tool_id in tool_ids) if tool_ids else "no runtime tools"
        base = f"I checked `{worker_id}` in the live registry and repo-backed catalog. They use loadout `{loadout.loadout_id}`, role `{role.role_id}`, and currently have {tools_text}."
        if detail_level == "technical":
            prompt_text = ", ".join(f"`{Path(ref).name}`" for ref in loadout.prompt_refs) or "no prompt refs"
            skill_text = ", ".join(f"`{Path(ref).name}`" for ref in loadout.skill_refs) or "no skill refs"
            return f"{base} Prompt refs: {prompt_text}. Skill refs: {skill_text}."
        return f"{base} They also have prompt and skill context loaded from the repo."

    def _tool_inventory_response(self, detail_level: str) -> str:
        tools = sorted(self.hub.tool_registry.list_all(), key=lambda item: item.tool_id)
        if detail_level == "technical":
            rows = [f"`{tool.tool_id}` ({tool.name}) -> {tool.implementation_ref}" for tool in tools[:20]]
            return "I checked the live tool registry and these tools are currently available:\n" + "\n".join(rows)
        rows = ", ".join(f"`{tool.tool_id}`" for tool in tools[:15])
        return f"I checked the live tool registry. Available tools include {rows}."

    def _delegation_response(self) -> str:
        worker_ids = [worker.worker_id for worker in self.hub.worker_registry.list_workers() if worker.worker_id in {"forge", "nova"}]
        if worker_ids:
            return "I checked the live worker registry. Vanta can lean on these workers for help: " + ", ".join(f"`{item}`" for item in worker_ids) + "."
        return "I checked the live worker registry. No additional workers are currently available for Vanta to delegate to."

    def _analyze_worker_capability(self, worker_id: str, query: str, detail_level: str) -> str:
        worker = self.hub.worker_registry.get_worker(worker_id)
        role = self.hub.worker_registry.get_role(worker.role_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        normalized_query = self._slugify(query) or ""
        query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        current_markers = set(loadout.allowed_tool_ids)
        current_markers.update(re.findall(r"[a-z0-9]+", role.purpose.lower()))
        current_markers.update(self._path_tokens(loadout.prompt_refs))
        current_markers.update(self._path_tokens(loadout.skill_refs))
        current_markers.update(tag.lower() for tag in getattr(worker, "tags", []))
        if normalized_query and any(normalized_query in marker or marker in normalized_query for marker in current_markers if marker):
            return self._capability_response(worker_id, loadout.loadout_id, query, "already_supported", detail_level)
        if query_tokens and query_tokens.intersection(current_markers):
            return self._capability_response(worker_id, loadout.loadout_id, query, "already_supported", detail_level)
        runtime_tool = None
        for tool in self.hub.tool_registry.list_all():
            markers = {tool.tool_id.lower(), tool.name.lower(), *(tag.lower() for tag in tool.capability_tags)}
            if normalized_query and any(normalized_query in marker or marker in normalized_query for marker in markers):
                runtime_tool = tool.tool_id
                break
            if query_tokens and query_tokens.intersection(set(re.findall(r"[a-z0-9]+", " ".join(markers)))):
                runtime_tool = tool.tool_id
                break
        if runtime_tool is not None:
            if runtime_tool in loadout.allowed_tool_ids:
                return self._capability_response(worker_id, loadout.loadout_id, query, "already_supported", detail_level, tool_id=runtime_tool)
            return self._capability_response(worker_id, loadout.loadout_id, query, "runtime_configurable", detail_level, tool_id=runtime_tool)
        return self._capability_response(worker_id, loadout.loadout_id, query, "code_change", detail_level)

    def _capability_response(self, worker_id: str, loadout_id: str, query: str, status: str, detail_level: str, *, tool_id: str | None = None) -> str:
        if status == "already_supported":
            if detail_level == "technical":
                reason = f"because `{tool_id}` is already available through `{loadout_id}`" if tool_id else f"based on loadout `{loadout_id}` and current worker context"
                return f"I checked `{worker_id}` and this looks already supported {reason}. Query: `{query}`."
            return f"I checked `{worker_id}` and this looks like something they can already handle."
        if status == "runtime_configurable":
            if detail_level == "technical":
                return f"I checked `{worker_id}`. The runtime already has `{tool_id}`, but `{loadout_id}` does not currently allow it, so this is a runtime config change rather than a code change."
            return f"I checked `{worker_id}` and this looks like a runtime config change, not a rebuild."
        if detail_level == "technical":
            return f"I checked `{worker_id}`, loadout `{loadout_id}`, the current tools, prompts, and skills. I do not see a runtime path for `{query}`, so this would need new executable behavior."
        return f"I checked `{worker_id}` and I do not see a built-in runtime path for that yet."

    def _grant_tool_intro(self, worker_id: str, loadout_id: str, tool_id: str, detail_level: str) -> str:
        if detail_level == "technical":
            return f"I checked `{worker_id}`. Loadout `{loadout_id}` does not currently allow `{tool_id}`, and I can update that runtime config now."
        return f"I checked `{worker_id}` and they do not have `{tool_id}` yet, but I can add it now."

    def _approval_needed_intro(self, worker_id: str, loadout_id: str, capability_name: str, detail_level: str) -> str:
        if detail_level == "technical":
            return (
                f"I checked `{worker_id}`, loadout `{loadout_id}`, and the current runtime tool registry. "
                f"I do not see a runtime tool for `{capability_name}`, so runtime config alone is not enough. "
                f"I'm preparing a code-change proposal next."
                f"{self._implementation_targets_text()}"
            )
        return (
            f"I checked `{worker_id}` and I do not see a built-in runtime path for `{capability_name}` yet, "
            f"so this needs an implementation proposal."
            f"{self._implementation_targets_text()}"
        )

    def _worker_tools_intro(self, worker_id: str, detail_level: str) -> str:
        if detail_level == "technical":
            return f"I checked `{worker_id}` and I'm inspecting the worker -> loadout -> allowed tools chain."
        return f"I checked `{worker_id}` and I'm looking at what tools they can use right now."

    def _worker_context_intro(self, worker_id: str, detail_level: str) -> str:
        if detail_level == "technical":
            return f"I checked `{worker_id}` and I'm pulling the role, loadout, prompt, and skill context."
        return f"I checked how `{worker_id}` is currently set up."

    def _create_worker_intro(self, draft: dict[str, Any], request: str) -> str:
        detail_level = self._detail_level(request)
        worker_id = str(draft.get("worker_id", "worker"))
        loadout_id = str(draft.get("loadout_id", "operator_core"))
        interface_mode = str(draft.get("interface_mode", "internal"))
        if detail_level == "technical":
            return f"I checked the runtime catalog and there is no existing worker conflict for `{worker_id}`. I can create it with loadout `{loadout_id}` in `{interface_mode}` mode and validate it."
        return f"I checked the current setup and I can create `{worker_id}` with a sensible runtime config."

    def _implementation_targets_text(self) -> str:
        worker_ids = {worker.worker_id for worker in self.hub.worker_registry.list_workers()}
        targets = [worker_id for worker_id in ("forge", "nova") if worker_id in worker_ids]
        if not targets:
            return ""
        return " Best internal help targets right now: " + " and ".join(f"`{item}`" for item in targets) + "."

    def _path_tokens(self, refs: list[str]) -> set[str]:
        tokens: set[str] = set()
        for ref in refs:
            tokens.update(re.findall(r"[a-z0-9]+", Path(ref).stem.lower()))
        return tokens

    def _session_key(self, payload: dict[str, Any]) -> str:
        source = str(payload.get("source", "unknown"))
        chat_id = payload.get("chat_id", "unknown")
        user_id = payload.get("user_id", "unknown")
        return f"{source}:{chat_id}:{user_id}"

    def _is_cancel_intent(self, text: str) -> bool:
        return text.lower().strip() in CANCEL_WORDS

    def _looks_like_topic_switch(self, text: str, pending: PendingAdminRequest) -> bool:
        lowered = text.lower().strip()
        if pending.session_type == "skill_approval":
            return lowered not in {"approve", "approved", "yes", "y", "reject", "rejected", "no", "n"} and self._looks_like_new_request(lowered)
        return self._looks_like_new_request(lowered)

    def _looks_like_new_request(self, lowered: str) -> bool:
        first = lowered.split(maxsplit=1)[0] if lowered else ""
        return lowered.startswith("/") or first in NEW_REQUEST_PREFIXES or "?" in lowered

    def _merge_follow_up(self, original_request: str, answer: str, blocker: str | None) -> str:
        cleaned = answer.strip()
        if blocker == "name":
            return f"{original_request} named {cleaned}"
        if blocker == "implementation_ref":
            return f"{original_request}\nImplementation reference: {cleaned}"
        if blocker == "bot_token":
            return f"{original_request}\nTelegram bot token: {cleaned}"
        if blocker == "model_name":
            return f"{original_request}\nUse model {cleaned}"
        if blocker == "schedule":
            return f"{original_request}\nSchedule: {cleaned}"
        if blocker == "destination":
            return f"{original_request}\nDestination: {cleaned}"
        if blocker == "capability_name":
            return f"{original_request}\nRequested capability: {cleaned}"
        if blocker == "improvement_target":
            return f"{original_request}\nDesired outcome: {cleaned}"
        if blocker == "worker_id":
            return f"{original_request}\nWorker: {cleaned}"
        return f"{original_request}\nAdditional context: {cleaned}"

    def _detail_level(self, text: str) -> str:
        lowered = text.lower()
        if any(term in lowered for term in TECHNICAL_TERMS) or "`" in text or "/" in text or "_" in text:
            return "technical"
        return "concise"

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

    def _is_worker_tools_question(self, lowered: str) -> bool:
        return "tool" in lowered and any(phrase in lowered for phrase in {"what tools", "which tools", "tools does", "tool access", "allowed tools"})

    def _is_worker_context_question(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"what loadout", "which loadout", "what role", "configured", "set up", "what prompts", "what skills"})

    def _is_worker_scope_question(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"that's it", "thats it", "that it", "only respond", "only use telegram", "only on telegram", "is that it"})

    def _is_tool_listing_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"list tools", "show tools", "what tools are available", "what are all the tools", "all the tools available", "inspect all tools", "available tools"})

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

    def _is_overview_request(self, lowered: str) -> bool:
        return all(token in lowered for token in {"hub", "workers", "tasks", "services"}) and any(
            phrase in lowered for phrase in {"inspect", "show", "status", "overview", "current"}
        )

    def _looks_like_capability_question(self, lowered: str, worker_id: str) -> bool:
        return any(prefix in lowered for prefix in {f"can {worker_id}", f"could {worker_id}", f"is {worker_id} able to"})

    def _is_delegation_question(self, lowered: str) -> bool:
        return ("vanta" in lowered or "you" in lowered) and any(word in lowered for word in {"delegate", "delegation", "call", "lean on", "use to help"})

    def _looks_like_repo_location_question(self, lowered: str) -> bool:
        return any(word in lowered for word in {"where", "defined", "file", "path"}) and any(word in lowered for word in {"repo", "soul", "prompt", "skill", "loadout", "worker", "tool"})

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

    def _is_create_tool_request(self, lowered: str) -> bool:
        return lowered == "create tool" or lowered.startswith("create a tool") or lowered.startswith("create new tool") or lowered.startswith("create a new tool") or ("tool" in lowered and any(word in lowered for word in CREATE_WORDS))

    def _is_create_worker_request(self, lowered: str) -> bool:
        return ("worker" in lowered or "bot" in lowered or "agent" in lowered) and any(word in lowered for word in CREATE_WORDS)

    def _looks_like_change_request(self, text: str) -> bool:
        lowered = text.lower().strip()
        return any(
            (
                self._is_create_tool_request(lowered),
                self._is_create_worker_request(lowered),
                self._looks_like_tool_grant_request(lowered),
                "attach" in lowered and "bot" in lowered,
                "reminder" in lowered and any(word in lowered for word in {"schedule", "scheduled", "daily", "weekly", "every"}),
                self._is_explicit_skill_request(lowered),
                self._looks_like_repeated_skill_gap(lowered),
                any(word in lowered for word in {"improve", "better", "upgrade", "refine"}),
                "start" in lowered and "bot" in lowered,
                "stop" in lowered and "bot" in lowered,
            )
        )

    def _looks_like_tool_grant_request(self, lowered: str) -> bool:
        if lowered.startswith("give me ") or lowered.startswith("show me ") or lowered.startswith("tell me "):
            return False
        return any(phrase in lowered for phrase in {"give ", "grant ", "allow ", "let ", "enable ", "can we give ", "can you give ", "i want to give "})

    def _is_explicit_skill_request(self, text: str) -> bool:
        lowered = text.lower()
        return "create a skill" in lowered or "make a skill" in lowered or "teach a skill" in lowered

    def _looks_like_repeated_skill_gap(self, text: str) -> bool:
        lowered = text.lower()
        return any(phrase in lowered for phrase in {"playbook", "consistent", "repeatable", "standard process", "triage"})

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

    def _extract_improvement_target(self, text: str) -> str | None:
        lowered = text.lower()
        match = re.search(r"(?:for|at)\s+([a-z0-9 _-]+)$", lowered)
        return match.group(1).strip() if match else None

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

    def _seed_tool_draft(self, text: str) -> dict[str, Any]:
        name = self._extract_name(text)
        return {
            "name": name,
            "tool_id": self._slugify(name) if name else None,
            "description": f"Runtime tool created from request: {text}",
            "implementation_ref": self._extract_implementation_ref(text),
            "capability_tags": self._extract_capability_tags(text),
            "safety_level": self._extract_safety_level(text),
        }

    def _seed_worker_draft(self, text: str) -> dict[str, Any]:
        name = self._extract_name(text)
        worker_id = self._slugify(name) if name else self._match_worker_id(text)
        role_id = self._infer_role(text)
        return {
            "worker_id": worker_id,
            "name": name or worker_id,
            "type_id": "agent_worker",
            "role_id": role_id,
            "loadout_id": self._default_loadout_for_role(role_id),
            "interface_mode": self._infer_interface_mode(text),
            "enabled": True,
            "tags": self._extract_capability_tags(text),
            "bot_token": self._extract_bot_token(text),
            "smoke_test": True,
        }

    def _title_case_fragment(self, value: str) -> str:
        cleaned = value.replace("_", " ").replace("-", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .!?`'\"")
        return " ".join(part.capitalize() for part in cleaned.split()) if cleaned else cleaned

    def _slugify(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return normalized or None

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

    def _repo_search_tokens(self, request: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9_]+", request.lower())
        ignored = {"the", "a", "an", "is", "are", "to", "of", "in", "on", "for", "can", "you", "tell", "me", "what", "which", "all", "currently", "available", "inspect"}
        result: list[str] = []
        for token in tokens:
            if len(token) < 3 or token in ignored or token in result:
                continue
            result.append(token)
        return result[:6]
