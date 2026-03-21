from __future__ import annotations

from abc import ABC, abstractmethod

from shared.schemas import AdapterHealth, AgentSpec, AgentTaskRecord


class AgentAdapter(ABC):
    def __init__(self, spec: AgentSpec) -> None:
        self.spec = spec

    @abstractmethod
    def describe(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> AdapterHealth:
        raise NotImplementedError

    @abstractmethod
    def submit_task(self, task: AgentTaskRecord) -> AgentTaskRecord:
        raise NotImplementedError

    @abstractmethod
    def get_task(self, task_id: str) -> AgentTaskRecord | None:
        raise NotImplementedError

    def cancel_task(self, task_id: str) -> AgentTaskRecord | None:
        return self.get_task(task_id)

    def send_message(self, message: str, thread_id: str = "") -> dict:
        return {"ok": False, "error": f"{self.spec.id} does not support direct messages"}
