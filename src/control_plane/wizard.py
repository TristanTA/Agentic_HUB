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
                "tools": ["trace_lookup", "file_read", "file_write", "workspace_note", "message_user"],
            },
        }
        self.store.upsert_telegram_session(session_key, state)
        return WizardResponse(
            text="New agent setup.\nStep 1/6: Send the agent name.",
            reply_markup=self._cancel_markup(),
        )

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
            return WizardResponse(
                text="Step 2/6: Send the agent purpose.",
                reply_markup=self._cancel_markup(),
            )

        if step == "purpose":
            data["purpose"] = clean_text
            state["step"] = "soul_prompt"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse(
                text="Step 3/6: Send a short soul prompt or operating style.",
                reply_markup=self._cancel_markup(),
            )

        if step == "soul_prompt":
            data["soul_prompt"] = clean_text
            state["step"] = "model"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse(
                text="Step 4/6: Choose a model.",
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

        if action == "model" and len(parts) >= 4:
            data["model"] = parts[3]
            state["step"] = "tools"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse(
                text="Step 5/6: Choose a tool set.",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "Minimal manager", "callback_data": "wizard:new_agent:tools:minimal_manager"}],
                        [{"text": "Workspace writer", "callback_data": "wizard:new_agent:tools:workspace_only"}],
                        [{"text": "Cancel", "callback_data": "wizard:new_agent:cancel"}],
                    ]
                },
            )

        if action == "tools" and len(parts) >= 4:
            preset = parts[3]
            if preset == "workspace_only":
                data["tools"] = ["workspace_note"]
            else:
                data["tools"] = ["trace_lookup", "file_read", "file_write", "workspace_note", "message_user"]
            state["step"] = "skills"
            self.store.upsert_telegram_session(session_key, state)
            return WizardResponse(
                text="Step 6/6: Choose skills.",
                reply_markup={
                    "inline_keyboard": [
                        [{"text": "General style", "callback_data": "wizard:new_agent:skills:general_style"}],
                        [{"text": "Planning checklist", "callback_data": "wizard:new_agent:skills:general_style,planning_checklist"}],
                        [{"text": "Cancel", "callback_data": "wizard:new_agent:cancel"}],
                    ]
                },
            )

        if action == "skills" and len(parts) >= 4:
            data["skills"] = [item.strip() for item in parts[3].split(",") if item.strip()]
            result = self.builder.create_agent(
                name=data["name"],
                purpose=data["purpose"],
                model=data["model"],
                skills=",".join(data["skills"]),
                tools=",".join(data["tools"]),
                soul_prompt=data.get("soul_prompt", ""),
            )
            self.store.delete_telegram_session(session_key)
            return WizardResponse(
                text=f"Created agent: {result['agent_id']}",
                final_result=result,
            )

        return None

    def _cancel_markup(self) -> dict:
        return {"inline_keyboard": [[{"text": "Cancel", "callback_data": "wizard:new_agent:cancel"}]]}
