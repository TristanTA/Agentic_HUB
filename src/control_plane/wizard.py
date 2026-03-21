from __future__ import annotations

from dataclasses import dataclass

from control_plane.builder_service import BuilderService
from storage.sqlite.db import SQLiteStore


@dataclass(slots=True)
class WizardResponse:
    text: str
    reply_markup: dict | None = None
    final_result: dict | None = None


class TelegramWizardService:
    def __init__(self, store: SQLiteStore, builder: BuilderService) -> None:
        self.store = store
        self.builder = builder

    def start_new_agent(self, session_key: str) -> WizardResponse:
        state = {
            "wizard": "new_agent",
            "step": "name",
            "data": {
                "model": "openai_gpt5_mini",
                "skills": ["general_style"],
                "tools": ["delegate_task", "get_task", "list_tasks", "message_user"],
                "exposure_mode": "internal_worker",
                "execution_mode": "native_hub",
                "adapter_type": "native",
                "telegram": {},
            },
        }
        self.store.upsert_telegram_session(session_key, state)
        return WizardResponse("New agent setup.\nStep 1/8: Send the agent name.", reply_markup=self._cancel_markup())

    def handle_text(self, session_key: str, text: str) -> WizardResponse | None:
        state = self.store.get_telegram_session(session_key)
        if not state or state.get("wizard") != "new_agent":
            return None

        step = state.get("step")
        data = state.setdefault("data", {})
        clean_text = (text or "").strip()

        if step == "name":
            data["name"] = clean_text
            state["step"] = "purpose"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse("Step 2/8: Send the agent purpose.", reply_markup=self._cancel_markup())

        if step == "purpose":
            data["purpose"] = clean_text
            state["step"] = "soul_prompt"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse("Step 3/8: Send a short soul prompt or operating style.", reply_markup=self._cancel_markup())

        if step == "soul_prompt":
            data["soul_prompt"] = clean_text
            state["step"] = "exposure_mode"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse(
                "Step 4/8: Choose how this agent is exposed.",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "Internal worker", "callback_data": "wizard:new_agent:exposure:internal_worker"}],
                        [{"text": "Hub addressable", "callback_data": "wizard:new_agent:exposure:hub_addressable"}],
                        [{"text": "Standalone Telegram", "callback_data": "wizard:new_agent:exposure:standalone_telegram"}],
                        [{"text": "Cancel", "callback_data": "wizard:new_agent:cancel"}],
                    ]
                },
            )

        if step == "telegram_token_env":
            data.setdefault("telegram", {})["bot_token_env"] = clean_text
            state["step"] = "telegram_default_chat"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse("Step 8/8: Send a default Telegram chat id for this direct-facing agent.", reply_markup=self._cancel_markup())

        if step == "telegram_default_chat":
            data.setdefault("telegram", {})["default_chat_id"] = clean_text
            return self._finalize_new_agent(session_key, state)

        if step == "external_command":
            data.setdefault("adapter_config", {})["command"] = clean_text
            if data.get("exposure_mode") == "standalone_telegram":
                state["step"] = "telegram_token_env"
                self.store.upsert_telegram_session(session_key, state)
                return WizardResponse("Step 7/8: Send the bot token env var name for this agent.", reply_markup=self._cancel_markup())
            return self._finalize_new_agent(session_key, state)

        return None

    def handle_callback(self, session_key: str, callback_data: str) -> WizardResponse | None:
        state = self.store.get_telegram_session(session_key)
        if not state or state.get("wizard") != "new_agent":
            return None

        parts = (callback_data or "").split(":")
        if len(parts) < 3:
            return None

        action = parts[2]
        data = state.setdefault("data", {})

        if action == "cancel":
            self.store.delete_telegram_session(session_key)
            return WizardResponse(text="Agent creation cancelled.")

        if action == "exposure" and len(parts) >= 4:
            data["exposure_mode"] = parts[3]
            state["step"] = "execution_mode"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse(
                "Step 5/8: Choose execution mode.",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "Native hub", "callback_data": "wizard:new_agent:execution:native_hub"}],
                        [{"text": "External adapter", "callback_data": "wizard:new_agent:execution:external_adapter"}],
                        [{"text": "Cancel", "callback_data": "wizard:new_agent:cancel"}],
                    ]
                },
            )

        if action == "execution" and len(parts) >= 4:
            data["execution_mode"] = parts[3]
            if parts[3] == "native_hub":
                data["adapter_type"] = "native"
                state["step"] = "model"
                self.store.upsert_telegram_session(session_key, state)
                return WizardResponse(
                    "Step 6/8: Choose a model.",
                    reply_markup={
                        "inline_keyboard": [
                            [
                                {"text": "GPT-5 Mini", "callback_data": "wizard:new_agent:model:openai_gpt5_mini"},
                                {"text": "Echo", "callback_data": "wizard:new_agent:model:echo_model"},
                            ],
                            [{"text": "Cancel", "callback_data": "wizard:new_agent:cancel"}],
                        ]
                    },
                )
            state["step"] = "adapter_type"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse(
                "Step 6/8: Choose an external adapter type.",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "Python process", "callback_data": "wizard:new_agent:adapter:python_process"}],
                        [{"text": "Telegram bot", "callback_data": "wizard:new_agent:adapter:telegram_bot"}],
                        [{"text": "OpenClaw", "callback_data": "wizard:new_agent:adapter:openclaw"}],
                        [{"text": "Cancel", "callback_data": "wizard:new_agent:cancel"}],
                    ]
                },
            )

        if action == "model" and len(parts) >= 4:
            data["model"] = parts[3]
            state["step"] = "tools"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse(
                "Step 7/8: Choose a tool set.",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "Minimal worker", "callback_data": "wizard:new_agent:tools:minimal_worker"}],
                        [{"text": "Operator worker", "callback_data": "wizard:new_agent:tools:operator_worker"}],
                        [{"text": "Cancel", "callback_data": "wizard:new_agent:cancel"}],
                    ]
                },
            )

        if action == "adapter" and len(parts) >= 4:
            adapter_type = parts[3]
            data["adapter_type"] = adapter_type
            data["model"] = "echo_model"
            if adapter_type == "python_process":
                state["step"] = "external_command"
                self.store.upsert_telegram_session(session_key, state)
                return WizardResponse("Step 7/8: Send the external command used to run this worker.", reply_markup=self._cancel_markup())
            data["adapter_config"] = {"bot_token_env": "", "chat_id": ""}
            if data.get("exposure_mode") == "standalone_telegram":
                state["step"] = "telegram_token_env"
                self.store.upsert_telegram_session(session_key, state)
                return WizardResponse("Step 7/8: Send the bot token env var name for this agent.", reply_markup=self._cancel_markup())
            return self._finalize_new_agent(session_key, state)

        if action == "tools" and len(parts) >= 4:
            preset = parts[3]
            if preset == "minimal_worker":
                data["tools"] = ["workspace_note", "message_user"]
            else:
                data["tools"] = ["delegate_task", "get_task", "list_tasks", "list_agents", "worker_health", "message_user"]
            state["step"] = "skills"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse(
                "Step 8/8: Choose skills.",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "General style", "callback_data": "wizard:new_agent:skills:general_style"}],
                        [{"text": "Planning + style", "callback_data": "wizard:new_agent:skills:general_style,planning_checklist"}],
                        [{"text": "Cancel", "callback_data": "wizard:new_agent:cancel"}],
                    ]
                },
            )

        if action == "skills" and len(parts) >= 4:
            data["skills"] = [item.strip() for item in parts[3].split(",") if item.strip()]
            if data.get("exposure_mode") == "standalone_telegram":
                state["step"] = "telegram_token_env"
                self.store.upsert_telegram_session(session_key, state)
                return WizardResponse("Direct-facing agent selected.\nSend the bot token env var name for this agent.", reply_markup=self._cancel_markup())
            return self._finalize_new_agent(session_key, state)

        return None

    def _finalize_new_agent(self, session_key: str, state: dict) -> WizardResponse:
        data = state["data"]
        if data.get("execution_mode") == "external_adapter":
            result = self.builder.attach_external_agent(
                name=data["name"],
                purpose=data["purpose"],
                adapter_type=data["adapter_type"],
                adapter_config=data.get("adapter_config", {}) | data.get("telegram", {}),
                exposure_mode=data["exposure_mode"],
                telegram=data.get("telegram", {}),
            )
        else:
            result = self.builder.create_agent(
                name=data["name"],
                purpose=data["purpose"],
                model=data["model"],
                skills=",".join(data.get("skills", ["general_style"])),
                tools=",".join(data.get("tools", ["workspace_note"])),
                soul_prompt=data.get("soul_prompt", ""),
                exposure_mode=data["exposure_mode"],
                execution_mode=data["execution_mode"],
                adapter_type=data["adapter_type"],
                telegram=data.get("telegram", {}),
                can_receive_tasks=True,
                can_receive_messages=data["exposure_mode"] != "internal_worker",
            )
        self.store.delete_telegram_session(session_key)
        return WizardResponse(text=f"Created agent: {result['agent_id']}", final_result=result)

    def _cancel_markup(self) -> dict:
        return {"inline_keyboard": [[{"text": "Cancel", "callback_data": "wizard:new_agent:cancel"}]]}
