from __future__ import annotations

from hub.adapters.base import AgentAdapter
from hub.adapters.external import PythonProcessAdapter, TelegramBotAdapter
from hub.adapters.native import NativeHubAdapter
from shared.schemas import AgentTaskRecord
from storage.sqlite.db import SQLiteStore


class AdapterRegistry:
    def __init__(self) -> None:
        self.adapters: dict[str, AgentAdapter] = {}

    def register(self, agent_id: str, adapter: AgentAdapter) -> None:
        self.adapters[agent_id] = adapter

    def get(self, agent_id: str) -> AgentAdapter | None:
        return self.adapters.get(agent_id)

    def list_agents(self) -> list[str]:
        return sorted(self.adapters)

    def health_report(self) -> list[dict]:
        return [adapter.health_check().model_dump() for adapter in self.adapters.values()]


def build_adapter(spec, *, hub_agent=None, store: SQLiteStore, context_factory=None) -> AgentAdapter:
    adapter_type = str(spec.adapter_type)
    if spec.execution_mode.value == "native_hub":
        if hub_agent is None or context_factory is None:
            raise ValueError(f"Native agent {spec.id} requires a runtime agent and context factory")
        return NativeHubAdapter(spec, hub_agent, store, context_factory)
    if adapter_type == "python_process":
        return PythonProcessAdapter(spec, store)
    if adapter_type in {"telegram_bot", "openclaw", "custom"}:
        return TelegramBotAdapter(spec, store)
    if spec.execution_mode.value == "external_adapter":
        return TelegramBotAdapter(spec, store)
    raise ValueError(f"Unsupported adapter configuration for {spec.id}")
