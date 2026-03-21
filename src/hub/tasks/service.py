from __future__ import annotations

import uuid

from hub.adapters.registry import AdapterRegistry
from shared.schemas import AgentTaskRecord
from storage.sqlite.db import SQLiteStore


class TaskService:
    def __init__(self, store: SQLiteStore, adapters: AdapterRegistry) -> None:
        self.store = store
        self.adapters = adapters

    def create_and_dispatch_task(
        self,
        *,
        created_by: str,
        assigned_to: str,
        goal: str,
        input_context: str,
        artifacts: list[str] | None = None,
    ) -> AgentTaskRecord:
        adapter = self.adapters.get(assigned_to)
        if adapter is None:
            raise ValueError(f"Unknown worker {assigned_to}")
        task = AgentTaskRecord(
            task_id=str(uuid.uuid4()),
            created_by=created_by,
            assigned_to=assigned_to,
            goal=goal,
            input_context=input_context,
            artifacts=artifacts or [],
            adapter_type=getattr(adapter.spec.adapter_type, "value", adapter.spec.adapter_type),
        )
        self.store.upsert_agent_task(task)
        return adapter.submit_task(task)

    def get_task(self, task_id: str) -> AgentTaskRecord | None:
        return self.store.get_agent_task(task_id)

    def list_tasks(self, *, assigned_to: str | None = None, created_by: str | None = None, limit: int = 20) -> list[AgentTaskRecord]:
        return self.store.list_agent_tasks(assigned_to=assigned_to, created_by=created_by, limit=limit)
