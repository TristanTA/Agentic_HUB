from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import requests

from agentic_hub.core.admin_executor import AdminExecutor
from agentic_hub.models.admin_action import AdminAction, AdminActionKind, AdminExecutionResult, VantaPlan
from agentic_hub.models.vanta_capability import VantaCapability


TOKEN_PATTERN = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]+\b")
CREATE_WORDS = {"create", "make", "new", "add", "build"}


@dataclass(frozen=True)
class VantaSystemConfig:
    system_id: str = "vanta_system_admin"
    display_name: str = "Vanta"
    locked: bool = True
    default_packs: tuple[str, ...] = ("default",)
    escalation_packs: tuple[str, ...] = ("repo", "web", "operator")


@dataclass
class PendingAdminRequest:
    session_type: Literal["field_collection", "skill_approval"]
    pending_action_kind: AdminActionKind | Literal["skill_approval"]
    original_text: str
    draft: dict[str, Any] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)


class VantaAdminAgent:
    SYSTEM_CONFIG = VantaSystemConfig()
    _CAPABILITIES: tuple[VantaCapability, ...] = (
        VantaCapability(
            capability_id="inspect_hub_status",
            label="inspect hub status",
            summary="Read overall hub health and counts.",
            action_kind="inspect_status",
            access="read",
            required_argument_names=["target"],
        ),
        VantaCapability(
            capability_id="list_workers",
            label="list workers",
            summary="Read worker inventory and interface modes.",
            action_kind="list_objects",
            access="read",
            required_argument_names=["kind"],
        ),
        VantaCapability(
            capability_id="list_tasks",
            label="list tasks",
            summary="Read scheduled task inventory.",
            action_kind="list_objects",
            access="read",
            required_argument_names=["kind"],
        ),
        VantaCapability(
            capability_id="list_services",
            label="list services",
            summary="Read registered services and states.",
            action_kind="list_services",
            access="read",
        ),
        VantaCapability(
            capability_id="inspect_logs",
            label="inspect logs",
            summary="Point users to slash-command log inspection.",
            access="read",
        ),
        VantaCapability(
            capability_id="create_worker",
            label="create worker",
            summary="Create an internal or managed worker in runtime overrides and validate it.",
            action_kind="create_worker",
            access="mutating",
            required_argument_names=["worker_id", "name", "type_id", "role_id", "loadout_id", "interface_mode"],
        ),
        VantaCapability(
            capability_id="create_loadout",
            label="create loadout",
            summary="Create a runtime loadout with tools and policies.",
            action_kind="create_loadout",
            access="mutating",
            required_argument_names=["loadout_id", "name"],
        ),
        VantaCapability(
            capability_id="create_tool",
            label="create tool",
            summary="Create a runtime tool definition for the hub catalog.",
            action_kind="create_tool",
            access="mutating",
            required_argument_names=["tool_id", "name", "description", "implementation_ref"],
        ),
        VantaCapability(
            capability_id="attach_managed_bot",
            label="attach managed bot",
            summary="Attach a Telegram bot token to an existing managed worker.",
            action_kind="attach_managed_bot",
            access="mutating",
            required_argument_names=["worker_id", "bot_token"],
        ),
        VantaCapability(
            capability_id="review_skills",
            label="review skills",
            summary="Generate a monthly skill review report.",
            action_kind="review_skills",
            access="read",
        ),
        VantaCapability(
            capability_id="request_code_change",
            label="request code change",
            summary="Draft an approval-gated repo change proposal.",
            action_kind="request_code_change",
            access="mutating",
            required_argument_names=["request_summary"],
            escalation_pack="repo",
        ),
        VantaCapability(
            capability_id="repo_context",
            label="repo context",
            summary="Fetch repo-oriented capability details when a task requires code changes.",
            access="read",
            escalation_pack="repo",
        ),
        VantaCapability(
            capability_id="web_context",
            label="web context",
            summary="Fetch web-oriented capability details when a task requires external research.",
            access="read",
            escalation_pack="web",
        ),
        VantaCapability(
            capability_id="operator_context",
            label="operator context",
            summary="Fetch broader operator capability details for privileged workflows.",
            access="read",
            escalation_pack="operator",
        ),
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
        capabilities = [capability for capability in self._CAPABILITIES if capability.escalation_pack in requested]
        return sorted(capabilities, key=lambda item: (item.escalation_pack, item.capability_id))

    def handle_message(self, text: str, payload: dict[str, Any]) -> str:
        session_key = self._session_key(payload)
        if session_key in self._sessions:
            return self._continue_session(session_key, text)

        plan = self._cheap_route(text)
        if plan is None:
            plan = self._plan_request(text)

        if plan.follow_up_question and plan.follow_up_field and plan.pending_action_kind:
            self._sessions[session_key] = PendingAdminRequest(
                session_type="field_collection",
                pending_action_kind=plan.pending_action_kind,
                original_text=text,
                draft=self._seed_draft(text, plan.pending_action_kind),
                required_fields=[plan.follow_up_field],
            )
            return plan.follow_up_question

        if not plan.actions:
            return plan.reply or self._fallback_reply()

        result = self.executor.execute(plan.actions)
        response = self._render_execution_result(result)
        return self._maybe_begin_skill_approval_session(session_key, plan.actions, result, response)

    def _continue_session(self, session_key: str, answer: str) -> str:
        session = self._sessions[session_key]
        if session.session_type == "skill_approval":
            decision = answer.strip().lower()
            skill_id = str(session.draft["skill_id"])
            loadout_ids = list(session.draft.get("target_loadout_ids", []))
            del self._sessions[session_key]
            if decision in {"approve", "approved", "yes", "y"}:
                result = self.executor.execute(
                    [AdminAction(kind="approve_skill", params={"skill_id": skill_id, "loadout_ids": loadout_ids}, summary=f"Approve skill {skill_id}")]
                )
                return self._render_execution_result(result)
            if decision in {"reject", "rejected", "no", "n"}:
                result = self.executor.execute(
                    [AdminAction(kind="reject_skill", params={"skill_id": skill_id}, summary=f"Reject skill {skill_id}")]
                )
                return self._render_execution_result(result)
            self._sessions[session_key] = session
            return "Please reply `approve` or `reject` for this skill proposal."

        if not session.required_fields:
            del self._sessions[session_key]
            return "I lost the admin context for that request. Please send it again."

        current_field = session.required_fields.pop(0)
        session.draft[current_field] = self._normalize_field(session.pending_action_kind, current_field, answer)

        follow_up = self._missing_field(session.pending_action_kind, session.draft)
        if follow_up:
            session.required_fields = [follow_up]
            return self._follow_up_question(session.pending_action_kind, follow_up, session.draft)

        actions = self._build_actions_for_kind(session.pending_action_kind, session.draft, session.original_text)
        del self._sessions[session_key]
        result = self.executor.execute(actions)
        return self._render_execution_result(result)

    def _cheap_route(self, text: str) -> VantaPlan | None:
        lowered = text.lower().strip()
        if not lowered:
            return VantaPlan(reply=self._fallback_reply())

        overview_actions = self._overview_actions(lowered)
        if overview_actions:
            return VantaPlan(actions=overview_actions)

        if self._is_worker_listing_request(lowered):
            return VantaPlan(actions=[AdminAction(kind="list_objects", params={"kind": "workers"}, summary="List workers")])
        if self._is_task_listing_request(lowered):
            return VantaPlan(actions=[AdminAction(kind="list_objects", params={"kind": "tasks"}, summary="List tasks")])
        if self._is_service_listing_request(lowered):
            return VantaPlan(actions=[AdminAction(kind="list_services", params={}, summary="List services")])
        if self._is_skill_listing_request(lowered):
            return VantaPlan(actions=[AdminAction(kind="list_skills", params={}, summary="List skills")])
        if self._is_skill_review_request(lowered):
            return VantaPlan(actions=[AdminAction(kind="review_skills", params={}, summary="Generate skill review report")])
        if self._is_hub_status_request(lowered):
            return VantaPlan(actions=[AdminAction(kind="inspect_status", params={"target": "hub"}, summary="Inspect hub status")])
        return None

    def _plan_request(self, text: str) -> VantaPlan:
        llm_plan = self._plan_with_llm(text)
        if llm_plan is not None:
            return llm_plan
        return self._plan_with_rules(text)

    def _plan_with_llm(self, text: str) -> VantaPlan | None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None

        packs = self._packs_for_text(text)
        manifest = self._manifest_prompt(packs)
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are Vanta, the Agentic Hub privileged admin planner. "
                                "You are not a normal worker. Plan only against the provided capability manifest. "
                                "Return valid JSON with actions, follow_up_question, follow_up_field, pending_action_kind, and reply. "
                                "Use request_code_change only for executable code or hard-coded behavior changes.\n\n"
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
            return VantaPlan.model_validate(json.loads(raw))
        except Exception:
            return None

    def _plan_with_rules(self, text: str) -> VantaPlan:
        lowered = text.lower().strip()
        if any(lowered.startswith(f"/{name}") for name in {"help", "status", "workers", "tasks", "inspect", "logs"}):
            return VantaPlan(reply="Use the slash command directly for operational lookups.")

        if self._is_explicit_skill_request(text):
            draft = self._seed_draft(text, "propose_skill")
            target_loadout_ids = draft.get("target_loadout_ids") or [draft.get("loadout_id", "operator_core")]
            return VantaPlan(
                actions=[
                    AdminAction(
                        kind="propose_skill",
                        params={"request_text": text, "target_loadout_ids": target_loadout_ids, "explicit": True},
                        summary="Draft a reusable skill proposal",
                    )
                ]
            )

        existing_worker_id = self._match_worker_id(text)
        if ("start" in lowered or "stop" in lowered) and "bot" in lowered and existing_worker_id:
            kind: AdminActionKind = "start_bot" if "start" in lowered else "stop_bot"
            return VantaPlan(actions=[AdminAction(kind=kind, params={"worker_id": existing_worker_id}, summary=f"{kind} for {existing_worker_id}")])

        if "attach" in lowered and "bot" in lowered:
            return self._plan_or_follow_up("attach_managed_bot", text)

        if self._is_create_tool_request(lowered):
            return self._plan_or_follow_up("create_tool", text)

        if self._is_create_worker_request(lowered):
            return self._plan_or_follow_up("create_worker", text)

        if any(word in lowered for word in {"inspect worker", "show worker", "worker status"}) and existing_worker_id:
            return VantaPlan(
                actions=[AdminAction(kind="inspect_status", params={"target": existing_worker_id}, summary=f"Inspect {existing_worker_id}")]
            )

        if self._looks_like_repeated_skill_gap(text):
            gap_record = self.hub.skill_library.record_gap(text, explicit=False)
            if self.hub.skill_library.should_propose(gap_record, explicit=False):
                draft = self._seed_draft(text, "propose_skill")
                target_loadout_ids = draft.get("target_loadout_ids") or [draft.get("loadout_id", "operator_core")]
                return VantaPlan(
                    actions=[
                        AdminAction(
                            kind="propose_skill",
                            params={"request_text": text, "target_loadout_ids": target_loadout_ids, "explicit": False},
                            summary="Draft a reusable skill proposal from repeated demand",
                        )
                    ]
                )
            return VantaPlan(reply="I noted that repeated capability request. If it keeps coming up, I’ll draft a reusable skill for approval.")

        return VantaPlan(reply=self._fallback_reply())

    def _plan_or_follow_up(self, kind: AdminActionKind, text: str) -> VantaPlan:
        draft = self._seed_draft(text, kind)
        missing = self._missing_field(kind, draft)
        if missing:
            return VantaPlan(
                follow_up_question=self._follow_up_question(kind, missing, draft),
                follow_up_field=missing,
                pending_action_kind=kind,
            )
        return VantaPlan(actions=self._build_actions_for_kind(kind, draft, text))

    def _build_actions_for_kind(self, kind: AdminActionKind, draft: dict[str, Any], original_text: str) -> list[AdminAction]:
        if kind == "create_worker":
            return self._build_worker_actions(draft, original_text)
        if kind == "attach_managed_bot":
            return [
                AdminAction(
                    kind="attach_managed_bot",
                    params={"worker_id": draft["worker_id"], "bot_token": draft["bot_token"]},
                    summary=f"Attach managed Telegram bot for {draft['worker_id']}",
                )
            ]
        if kind == "create_tool":
            return [
                AdminAction(
                    kind="create_tool",
                    params={
                        "tool_id": draft["tool_id"],
                        "name": draft["name"],
                        "description": draft["description"],
                        "implementation_ref": draft["implementation_ref"],
                        "capability_tags": draft.get("capability_tags", []),
                        "safety_level": draft.get("safety_level", "low"),
                    },
                    summary=f"Create tool {draft['tool_id']}",
                )
            ]
        raise ValueError(f"Unsupported pending action kind: {kind}")

    def _build_worker_actions(self, draft: dict[str, Any], original_text: str) -> list[AdminAction]:
        if draft.get("needs_code_change"):
            summary = (
                f"Draft a code change for worker `{draft['worker_id']}` so it can {draft['requested_capability']} "
                f"using model `{draft.get('model_name', 'unspecified')}`."
            )
            return [
                AdminAction(
                    kind="request_code_change",
                    params={
                        "request_summary": summary,
                        "worker_id": draft["worker_id"],
                        "original_request": original_text,
                    },
                    summary=summary,
                    requires_approval=True,
                )
            ]

        params = {
            "worker_id": draft["worker_id"],
            "name": draft["name"],
            "type_id": draft.get("type_id", "agent_worker"),
            "role_id": draft.get("role_id", "operator"),
            "loadout_id": draft.get("loadout_id", self._default_loadout_for_role(draft.get("role_id", "operator"))),
            "interface_mode": draft.get("interface_mode", "internal"),
            "enabled": True,
            "owner": "vanta",
            "notes": draft.get("notes", f"Created by Vanta from chat request: {original_text}"),
            "tags": draft.get("tags", ["runtime", "vanta"]),
            "assigned_queues": ["default"],
            "smoke_test": True,
        }
        if draft.get("bot_token"):
            params["bot_token"] = draft["bot_token"]
        return [AdminAction(kind="create_worker", params=params, summary=f"Create worker {draft['worker_id']}")]

    def _seed_draft(self, text: str, kind: AdminActionKind | str) -> dict[str, Any]:
        draft: dict[str, Any] = {}
        if kind in {"create_worker", "attach_managed_bot", "propose_skill"}:
            name = self._extract_name(text)
            if name:
                draft["name"] = name
                draft["worker_id"] = self._slugify(name)

            worker_id = self._match_worker_id(text)
            if worker_id:
                draft["worker_id"] = worker_id
                if "name" not in draft:
                    worker = self.hub.worker_registry.get_worker(worker_id)
                    draft["name"] = worker.name

            draft["type_id"] = self._match_known_id(text, [item.type_id for item in self.hub.worker_registry.list_types()]) or "agent_worker"
            draft["role_id"] = self._match_known_id(text, [item.role_id for item in self.hub.worker_registry.list_roles()]) or self._infer_role(text)
            draft["loadout_id"] = self._match_known_id(text, [item.loadout_id for item in self.hub.worker_registry.list_loadouts()]) or self._default_loadout_for_role(draft["role_id"])
            draft["target_loadout_ids"] = [draft["loadout_id"]]
            draft["interface_mode"] = self._infer_interface_mode(text)
            token = TOKEN_PATTERN.search(text)
            if token:
                draft["bot_token"] = token.group(0)

            capability = self._extract_requested_capability(text)
            if capability:
                draft["requested_capability"] = capability
                draft["needs_code_change"] = True

            model_name = self._extract_model_name(text)
            if model_name:
                draft["model_name"] = model_name
            return draft

        if kind == "create_tool":
            name = self._extract_name(text)
            if name:
                draft["name"] = name
                draft["tool_id"] = self._slugify(name)
            tool_id = self._match_tool_id(text)
            if tool_id:
                draft["tool_id"] = tool_id
                if "name" not in draft:
                    draft["name"] = tool_id.replace("_", " ").title()
            implementation_ref = self._extract_implementation_ref(text)
            if implementation_ref:
                draft["implementation_ref"] = implementation_ref
            draft["description"] = text.strip().rstrip(".")
            safety_level = self._extract_safety_level(text)
            if safety_level:
                draft["safety_level"] = safety_level
            tags = self._extract_capability_tags(text)
            if tags:
                draft["capability_tags"] = tags
        return draft

    def _missing_field(self, kind: AdminActionKind, draft: dict[str, Any]) -> str | None:
        if kind == "create_worker":
            if "name" not in draft:
                return "name"
            if draft.get("interface_mode") == "managed" and "bot_token" not in draft:
                return "bot_token"
            if draft.get("needs_code_change") and "model_name" not in draft:
                return "model_name"
            return None
        if kind == "attach_managed_bot":
            if "worker_id" not in draft:
                return "worker_id"
            if "bot_token" not in draft:
                return "bot_token"
            return None
        if kind == "create_tool":
            if "name" not in draft:
                return "name"
            if "implementation_ref" not in draft:
                return "implementation_ref"
            return None
        return None

    def _follow_up_question(self, kind: AdminActionKind, field_name: str, draft: dict[str, Any]) -> str:
        if field_name == "name":
            if kind == "create_tool":
                return "What should I call the tool?"
            return "What should I call the worker?"
        if field_name == "bot_token":
            return f"What Telegram bot token should I attach to `{draft.get('worker_id', 'that worker')}`?"
        if field_name == "model_name":
            return "What model should this worker use?"
        if field_name == "worker_id":
            return "Which worker should I attach the managed Telegram bot to?"
        if field_name == "implementation_ref":
            return f"What implementation reference should I use for `{draft.get('tool_id', 'that tool')}`?"
        return f"I need one more detail: {field_name}."

    def _normalize_field(self, kind: AdminActionKind | Literal["skill_approval"], field_name: str, answer: str) -> Any:
        value = answer.strip()
        if field_name == "name":
            return value
        if field_name == "worker_id":
            return self._slugify(value)
        if field_name == "implementation_ref":
            return value
        if kind == "create_tool" and field_name == "tool_id":
            return self._slugify(value)
        return value

    def _render_execution_result(self, result: AdminExecutionResult) -> str:
        if result.status in {"approval_required", "failed"}:
            return result.summary
        validation_lines: list[str] = []
        for action_result in result.action_results:
            validation_lines.extend(action_result.validation_results)
        if not validation_lines:
            return result.summary
        return "\n".join([result.summary, "", "Validation:", *[f"- {line}" for line in validation_lines]])

    def _session_key(self, payload: dict[str, Any]) -> str:
        return f"{payload.get('source', 'local')}:{payload.get('chat_id', 'default')}:{payload.get('user_id', 'anon')}"

    def _manifest_prompt(self, packs: list[str]) -> str:
        capability_lines = []
        for capability in self.get_capability_manifest(packs):
            required = ", ".join(capability.required_argument_names) or "none"
            capability_lines.append(
                f"- {capability.capability_id}: {capability.label} | pack={capability.escalation_pack} | "
                f"access={capability.access} | requires={required} | {capability.summary}"
            )
        return "Capability manifest:\n" + "\n".join(capability_lines)

    def _packs_for_text(self, text: str) -> list[str]:
        lowered = text.lower()
        packs = set(self.SYSTEM_CONFIG.default_packs)
        if any(word in lowered for word in {"code", "repo", "file", "patch", "implementation"}):
            packs.add("repo")
        if any(word in lowered for word in {"web", "research", "search", "fetch", "look up"}):
            packs.add("web")
        if any(word in lowered for word in {"operator", "privileged", "escalate"}):
            packs.add("operator")
        return sorted(packs)

    def _overview_actions(self, lowered: str) -> list[AdminAction]:
        actions: list[AdminAction] = []
        if ("status" in lowered or "inspect current" in lowered or "overview" in lowered) and ("hub" in lowered or "services" in lowered or "workers" in lowered or "tasks" in lowered):
            actions.append(AdminAction(kind="inspect_status", params={"target": "hub"}, summary="Inspect hub status"))
            if "workers" in lowered:
                actions.append(AdminAction(kind="list_objects", params={"kind": "workers"}, summary="List workers"))
            if "tasks" in lowered:
                actions.append(AdminAction(kind="list_objects", params={"kind": "tasks"}, summary="List tasks"))
            if "services" in lowered:
                actions.append(AdminAction(kind="list_services", params={}, summary="List services"))
        return actions

    def _is_worker_listing_request(self, lowered: str) -> bool:
        return any(
            phrase in lowered
            for phrase in {
                "list workers",
                "show workers",
                "which workers",
                "what are the workers",
                "what workers",
                "all workers",
                "active workers",
            }
        )

    def _is_task_listing_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"list tasks", "show tasks", "what are the tasks", "active tasks"})

    def _is_service_listing_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"list services", "show services", "what are the services"})

    def _is_skill_listing_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"list skills", "show skills", "which skills"})

    def _is_skill_review_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"review skills", "monthly skill review", "skill review"})

    def _is_hub_status_request(self, lowered: str) -> bool:
        return any(phrase in lowered for phrase in {"hub status", "inspect hub", "show hub status"})

    def _is_create_worker_request(self, lowered: str) -> bool:
        return bool(CREATE_WORDS.intersection(lowered.split())) and any(word in lowered for word in {"worker", "agent", "telegram bot"})

    def _is_create_tool_request(self, lowered: str) -> bool:
        return bool(CREATE_WORDS.intersection(lowered.split())) and "tool" in lowered

    def _extract_name(self, text: str) -> str | None:
        patterns = [
            r"(?:named|called)\s+([A-Za-z0-9 _-]+)",
            r"new (?:internal |managed |hybrid )?(?:worker|agent|telegram bot|tool)\s+([A-Za-z0-9 _-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip().strip(".?!")
        return None

    def _match_worker_id(self, text: str) -> str | None:
        lowered = text.lower()
        for worker_id in self.hub.worker_registry.worker_ids():
            if worker_id.lower() in lowered:
                return worker_id
        return None

    def _match_tool_id(self, text: str) -> str | None:
        lowered = text.lower()
        for tool in self.hub.catalog_manager.list_objects("tools"):
            if tool.tool_id.lower() in lowered:
                return tool.tool_id
        return None

    def _match_known_id(self, text: str, values: list[str]) -> str | None:
        lowered = text.lower()
        for value in values:
            if value.lower() in lowered:
                return value
        return None

    def _infer_interface_mode(self, text: str) -> str:
        lowered = text.lower()
        if "managed" in lowered or "telegram bot" in lowered:
            return "managed"
        if "hybrid" in lowered:
            return "hybrid"
        return "internal"

    def _infer_role(self, text: str) -> str:
        lowered = text.lower()
        if "research" in lowered:
            return "researcher"
        if "review" in lowered:
            return "reviewer"
        if "coordinate" in lowered:
            return "coordinator"
        return "operator"

    def _default_loadout_for_role(self, role_id: str) -> str:
        return {
            "operator": "operator_core",
            "researcher": "research_core",
            "reviewer": "review_core",
            "coordinator": "coordinator_core",
            "band_assistant": "aria_band_core",
        }.get(role_id, "operator_core")

    def _extract_requested_capability(self, text: str) -> str | None:
        lowered = text.lower()
        if "on command" in lowered or re.search(r"\bthat\s+(creates|generates|builds|does)\b", lowered):
            return text.strip()
        return None

    def _extract_model_name(self, text: str) -> str | None:
        lowered = text.lower()
        if "nano-banana" in lowered:
            return "Nano-banana"
        match = re.search(r"model\s+([A-Za-z0-9._-]+)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        return None

    def _extract_implementation_ref(self, text: str) -> str | None:
        match = re.search(r"(agentic_hub\.[A-Za-z0-9_./-]+|[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+)", text)
        if match:
            return match.group(1)
        return None

    def _extract_safety_level(self, text: str) -> str | None:
        lowered = text.lower()
        for level in ("low", "medium", "high"):
            if f"safety {level}" in lowered or f"{level} safety" in lowered:
                return level
        return None

    def _extract_capability_tags(self, text: str) -> list[str]:
        lowered = text.lower()
        tags = []
        for tag in ("hub", "admin", "telegram", "repo", "web", "skill"):
            if tag in lowered:
                tags.append(tag)
        return tags

    def _slugify(self, value: str) -> str:
        slug = value.strip().lower().replace(" ", "_")
        return "".join(ch for ch in slug if ch.isalnum() or ch == "_")

    def _looks_like_repeated_skill_gap(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            phrase in lowered
            for phrase in {
                "we need",
                "keep needing",
                "often need",
                "repeatedly need",
                "remember how to",
                "should know how to",
            }
        )

    def _is_explicit_skill_request(self, text: str) -> bool:
        lowered = text.lower()
        return any(phrase in lowered for phrase in {"make a skill", "create a skill", "build a skill", "draft a skill"})

    def _maybe_begin_skill_approval_session(
        self,
        session_key: str,
        actions: list[AdminAction],
        result: AdminExecutionResult,
        rendered: str,
    ) -> str:
        if result.status != "completed":
            return rendered
        proposal_action = next((action for action in actions if action.kind == "propose_skill"), None)
        if proposal_action is None:
            return rendered
        changed_ids = [item for action_result in result.action_results for item in action_result.changed_ids]
        if not changed_ids:
            return rendered
        self._sessions[session_key] = PendingAdminRequest(
            session_type="skill_approval",
            pending_action_kind="skill_approval",
            original_text=str(proposal_action.params["request_text"]),
            draft={
                "skill_id": changed_ids[0],
                "target_loadout_ids": list(proposal_action.params.get("target_loadout_ids", [])),
            },
        )
        return "\n".join([rendered, "", "Approve this skill? Reply `approve` or `reject`."])

    def _fallback_reply(self) -> str:
        labels = ", ".join(capability.label for capability in self.default_capabilities() if capability.escalation_pack == "default")
        return (
            "I can handle hub admin tasks in plain English. "
            f"Default capabilities: {labels}. "
            "For direct operational checks, slash commands still work."
        )
