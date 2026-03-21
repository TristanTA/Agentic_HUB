from __future__ import annotations

from datetime import datetime, timezone

from hub.adapters.base import AgentAdapter
from hub.agents.factory import HubAgent
from shared.schemas import AdapterHealth, AgentContext, AgentTaskRecord, TaskStatus
from storage.sqlite.db import SQLiteStore


class NativeHubAdapter(AgentAdapter):
    def __init__(
        self,
        spec,
        agent: HubAgent,
        store: SQLiteStore,
        context_factory,
    ) -> None:
        super().__init__(spec)
        self.agent = agent
        self.store = store
        self.context_factory = context_factory

    def describe(self) -> dict:
        return {"agent_id": self.spec.id, "adapter_type": "native", "execution_mode": self.spec.execution_mode.value}

    def health_check(self) -> AdapterHealth:
        return AdapterHealth(adapter_type="native", agent_id=self.spec.id, status="ok")

    def submit_task(self, task: AgentTaskRecord) -> AgentTaskRecord:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        self.store.upsert_agent_task(task)
        try:
            context = self.context_factory(self.spec.id, task.goal, task.input_context)
            response = self.agent.handle(context, task.input_context)
            task.status = TaskStatus.COMPLETED
            task.result_summary = response.output_text[:240]
            task.result_payload = {"output_text": response.output_text}
            task.completed_at = datetime.now(timezone.utc)
            self.store.upsert_agent_task(task)
            return task
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = f"{type(exc).__name__}: {exc}"
            task.completed_at = datetime.now(timezone.utc)
            self.store.upsert_agent_task(task)
            return task

    def get_task(self, task_id: str) -> AgentTaskRecord | None:
        return self.store.get_agent_task(task_id)
