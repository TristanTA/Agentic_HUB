from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import requests

from agentic_hub.core.admin_executor import AdminExecutor
from agentic_hub.models.admin_action import AdminAction, AdminExecutionResult, VantaPlan


TOKEN_PATTERN = re.compile(r"\b\d{5,}:[A-Za-z0-9_-]+\b")


@dataclass
class PendingAdminRequest:
    intent: str
    original_text: str
    draft: dict[str, Any] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)


class VantaAdminAgent:
    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self.executor = AdminExecutor(hub)
        self._sessions: dict[str, PendingAdminRequest] = {}

    def handle_message(self, text: str, payload: dict[str, Any]) -> str:
        session_key = self._session_key(payload)
        if session_key in self._sessions:
            return self._continue_session(session_key, text)

        plan = self._plan_request(text)
        if plan.follow_up_question and plan.follow_up_field:
            self._sessions[session_key] = PendingAdminRequest(
                intent=self._infer_intent(text),
                original_text=text,
                draft=self._seed_draft(text),
                required_fields=[plan.follow_up_field],
            )
            return plan.follow_up_question

        if not plan.actions:
            return plan.reply or "I can help with workers, loadouts, managed Telegram bots, status checks, and runtime admin setup."

        result = self.executor.execute(plan.actions)
        return self._render_execution_result(result)

    def _continue_session(self, session_key: str, answer: str) -> str:
        session = self._sessions[session_key]
        current_field = session.required_fields.pop(0)
        session.draft[current_field] = self._normalize_field(current_field, answer)

        if session.intent == "create_worker":
            follow_up = self._missing_worker_field(session.draft)
            if follow_up:
                session.required_fields = [follow_up]
                return self._follow_up_question(follow_up, session.draft)
            actions = self._build_worker_actions(session.draft, session.original_text)
        elif session.intent == "attach_managed_bot":
            follow_up = self._missing_bot_field(session.draft)
            if follow_up:
                session.required_fields = [follow_up]
                return self._follow_up_question(follow_up, session.draft)
            actions = [
                AdminAction(
                    kind="attach_managed_bot",
                    params={"worker_id": session.draft["worker_id"], "bot_token": session.draft["bot_token"]},
                    summary=f"Attach managed Telegram bot for {session.draft['worker_id']}",
                )
            ]
        else:
            del self._sessions[session_key]
            return "I lost the admin context for that request. Please send it again."

        del self._sessions[session_key]
        result = self.executor.execute(actions)
        return self._render_execution_result(result)

    def _plan_request(self, text: str) -> VantaPlan:
        llm_plan = self._plan_with_llm(text)
        if llm_plan is not None:
            return llm_plan
        return self._plan_with_rules(text)

    def _plan_with_llm(self, text: str) -> VantaPlan | None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None

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
                                "You are Vanta, the Agentic Hub admin planner. "
                                "Return valid JSON with actions, follow_up_question, follow_up_field, and reply. "
                                "Allowed action kinds: create_worker, update_worker, create_loadout, attach_managed_bot, "
                                "start_bot, stop_bot, run_smoke_test, inspect_status, list_objects, request_code_change. "
                                "Only use request_code_change when executable code or hard-coded behavior must change."
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

        if any(word in lowered for word in {"list workers", "show workers", "which workers"}):
            return VantaPlan(actions=[AdminAction(kind="list_objects", params={"kind": "workers"}, summary="List workers")])
        if any(word in lowered for word in {"list loadouts", "show loadouts"}):
            return VantaPlan(actions=[AdminAction(kind="list_objects", params={"kind": "loadouts"}, summary="List loadouts")])
        if any(word in lowered for word in {"hub status", "inspect hub", "show hub status"}):
            return VantaPlan(actions=[AdminAction(kind="inspect_status", params={"target": "hub"}, summary="Inspect hub status")])

        existing_worker_id = self._match_worker_id(text)
        if ("start" in lowered or "stop" in lowered) and "bot" in lowered and existing_worker_id:
            kind = "start_bot" if "start" in lowered else "stop_bot"
            return VantaPlan(actions=[AdminAction(kind=kind, params={"worker_id": existing_worker_id}, summary=f"{kind} for {existing_worker_id}")])

        if "attach" in lowered and "bot" in lowered:
            draft = self._seed_draft(text)
            missing = self._missing_bot_field(draft)
            if missing:
                return VantaPlan(follow_up_question=self._follow_up_question(missing, draft), follow_up_field=missing)
            return VantaPlan(
                actions=[
                    AdminAction(
                        kind="attach_managed_bot",
                        params={"worker_id": draft["worker_id"], "bot_token": draft["bot_token"]},
                        summary=f"Attach managed Telegram bot for {draft['worker_id']}",
                    )
                ]
            )

        if any(word in lowered for word in {"create", "make", "new"}) and any(word in lowered for word in {"worker", "agent", "telegram bot"}):
            draft = self._seed_draft(text)
            missing = self._missing_worker_field(draft)
            if missing:
                return VantaPlan(follow_up_question=self._follow_up_question(missing, draft), follow_up_field=missing)
            return VantaPlan(actions=self._build_worker_actions(draft, text))

        if any(word in lowered for word in {"inspect worker", "show worker", "worker status"}) and existing_worker_id:
            return VantaPlan(
                actions=[AdminAction(kind="inspect_status", params={"target": existing_worker_id}, summary=f"Inspect {existing_worker_id}")]
            )

        return VantaPlan(
            reply=(
                "I can create or update workers, create loadouts, attach managed Telegram bots, start or stop bots, "
                "and inspect hub or worker status. Ask in plain English and I’ll translate it into runtime admin actions."
            )
        )

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

    def _seed_draft(self, text: str) -> dict[str, Any]:
        draft: dict[str, Any] = {}
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

    def _missing_worker_field(self, draft: dict[str, Any]) -> str | None:
        if "name" not in draft:
            return "name"
        if draft.get("interface_mode") == "managed" and "bot_token" not in draft:
            return "bot_token"
        if draft.get("needs_code_change") and "model_name" not in draft:
            return "model_name"
        return None

    def _missing_bot_field(self, draft: dict[str, Any]) -> str | None:
        if "worker_id" not in draft:
            return "worker_id"
        if "bot_token" not in draft:
            return "bot_token"
        return None

    def _follow_up_question(self, field_name: str, draft: dict[str, Any]) -> str:
        if field_name == "name":
            return "What should I call the worker?"
        if field_name == "bot_token":
            return f"What Telegram bot token should I attach to `{draft.get('worker_id', 'that worker')}`?"
        if field_name == "model_name":
            return "What model should this worker use?"
        if field_name == "worker_id":
            return "Which worker should I attach the managed Telegram bot to?"
        return f"I need one more detail: {field_name}."

    def _normalize_field(self, field_name: str, answer: str) -> Any:
        value = answer.strip()
        if field_name == "name":
            return value
        if field_name == "worker_id":
            return self._slugify(value)
        return value

    def _render_execution_result(self, result: AdminExecutionResult) -> str:
        if result.status == "approval_required":
            return result.summary
        if result.status == "failed":
            return result.summary
        validation_lines: list[str] = []
        for action_result in result.action_results:
            validation_lines.extend(action_result.validation_results)
        if not validation_lines:
            return result.summary
        return "\n".join([result.summary, "", "Validation:", *[f"- {line}" for line in validation_lines]])

    def _session_key(self, payload: dict[str, Any]) -> str:
        return f"{payload.get('source', 'local')}:{payload.get('chat_id', 'default')}:{payload.get('user_id', 'anon')}"

    def _infer_intent(self, text: str) -> str:
        lowered = text.lower()
        if "attach" in lowered and "bot" in lowered:
            return "attach_managed_bot"
        return "create_worker"

    def _extract_name(self, text: str) -> str | None:
        patterns = [
            r"(?:named|called)\s+([A-Za-z0-9 _-]+)",
            r"new (?:internal |managed |hybrid )?(?:worker|agent|telegram bot)\s+([A-Za-z0-9 _-]+)",
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

    def _slugify(self, value: str) -> str:
        slug = value.strip().lower().replace(" ", "_")
        return "".join(ch for ch in slug if ch.isalnum() or ch == "_")
