from __future__ import annotations

from shared.schemas import AgentInterface, AgentRole, ModelProfile, SkillProfile, ToolProfile
from specs.service import AgentSpecService
from storage.sqlite.db import SQLiteStore


class AgentInterviewService:
    def __init__(self, store: SQLiteStore, specs: AgentSpecService) -> None:
        self.store = store
        self.specs = specs

    def start(self, session_key: str) -> str:
        self.store.upsert_telegram_session(
            session_key,
            {"wizard": "agent_spec", "step": "id", "data": {}},
        )
        return "New agent interview.\nStep 1/7: Send the agent id."

    def handle_text(self, session_key: str, text: str) -> str | None:
        state = self.store.get_telegram_session(session_key)
        if not state or state.get("wizard") != "agent_spec":
            return None
        step = state.get("step")
        data = state.setdefault("data", {})
        clean = (text or "").strip()
        if step == "id":
            data["id"] = clean
            state["step"] = "purpose"
            self.store.upsert_telegram_session(session_key, state)
            return "Step 2/7: Send the primary purpose."
        if step == "purpose":
            data["purpose"] = clean
            state["step"] = "role"
            self.store.upsert_telegram_session(session_key, state)
            return f"Step 3/7: Send the role type: {', '.join(item.value for item in AgentRole if item != AgentRole.SUPERVISOR)}"
        if step == "role":
            if clean not in {item.value for item in AgentRole}:
                return f"Invalid role. Use one of: {', '.join(item.value for item in AgentRole)}"
            data["role"] = clean
            state["step"] = "interface"
            self.store.upsert_telegram_session(session_key, state)
            return f"Step 4/7: Send the interface: {', '.join(item.value for item in AgentInterface)}"
        if step == "interface":
            if clean not in {item.value for item in AgentInterface}:
                return f"Invalid interface. Use one of: {', '.join(item.value for item in AgentInterface)}"
            data["interface"] = clean
            state["step"] = "autonomy_level"
            self.store.upsert_telegram_session(session_key, state)
            return "Step 5/7: Send the autonomy level (for example: bounded, direct, supervised)."
        if step == "autonomy_level":
            data["autonomy_level"] = clean
            state["step"] = "model_profile"
            self.store.upsert_telegram_session(session_key, state)
            return f"Step 6/7: Send the model profile: {', '.join(item.value for item in ModelProfile)}"
        if step == "model_profile":
            if clean not in {item.value for item in ModelProfile}:
                return f"Invalid model profile. Use one of: {', '.join(item.value for item in ModelProfile)}"
            data["model_profile"] = clean
            state["step"] = "tool_profile"
            self.store.upsert_telegram_session(session_key, state)
            return f"Step 7/7: Send the tool profile: {', '.join(item.value for item in ToolProfile)}"
        if step == "tool_profile":
            if clean not in {item.value for item in ToolProfile}:
                return f"Invalid tool profile. Use one of: {', '.join(item.value for item in ToolProfile)}"
            spec = self.specs.create_draft(
                agent_id=data["id"],
                purpose=data["purpose"],
                role=AgentRole(data["role"]),
                interface=AgentInterface(data["interface"]),
                autonomy_level=data["autonomy_level"],
                model_profile=ModelProfile(data["model_profile"]),
                tool_profile=ToolProfile(clean),
                skill_profile=SkillProfile.PLANNING if data["role"] == AgentRole.PLANNER.value else SkillProfile.GENERAL,
            )
            self.store.delete_telegram_session(session_key)
            return (
                f"Created draft spec: {spec.id}\n"
                f"Role: {spec.role.value}\n"
                f"Interface: {spec.interface.value}\n"
                f"Status: {spec.status.value}\n"
                f"Next: /validate_agent {spec.id}"
            )
        return None
