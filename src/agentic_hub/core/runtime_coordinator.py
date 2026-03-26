from __future__ import annotations

from typing import Dict, Optional

from agentic_hub.core.approval_manager import ApprovalManager
from agentic_hub.core.artifact_store import ArtifactStore
from agentic_hub.core.dispatcher import Dispatcher
from agentic_hub.core.event_log import EventLog
from agentic_hub.core.memory_manager import MemoryManager
from agentic_hub.core.policy_resolver import PolicyResolver
from agentic_hub.core.worker_adapter import WorkerAdapter
from agentic_hub.core.worker_runner import WorkerRunner
from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.models.task import Task
from agentic_hub.models.task_result import TaskResult


class RuntimeCoordinator:
    """
    Thin runtime layer that turns registries + policies + dispatcher + runner
    into a single callable execution surface.

    This is the bridge between:
    - static architecture objects (schemas/registries)
    - actual task execution
    """

    def __init__(
        self,
        worker_registry: WorkerRegistry,
        tool_registry: ToolRegistry,
        *,
        approval_manager: ApprovalManager | None = None,
        artifact_store: ArtifactStore | None = None,
        event_log: EventLog | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.worker_registry = worker_registry
        self.tool_registry = tool_registry
        self.approval_manager = approval_manager or ApprovalManager()
        self.artifact_store = artifact_store or ArtifactStore()
        self.event_log = event_log or EventLog()
        self.memory_manager = memory_manager or MemoryManager()

        self.policy_resolver = PolicyResolver(worker_registry, tool_registry)
        self.dispatcher = Dispatcher(worker_registry, self.policy_resolver)
        self.runner = WorkerRunner(
            policy_resolver=self.policy_resolver,
            approval_manager=self.approval_manager,
            artifact_store=self.artifact_store,
            event_log=self.event_log,
        )

        self._adapters_by_type: Dict[str, WorkerAdapter] = {}

    def register_adapter(self, worker_type_id: str, adapter: WorkerAdapter) -> None:
        self._adapters_by_type[worker_type_id] = adapter

    def get_adapter(self, worker_type_id: str) -> WorkerAdapter:
        try:
            return self._adapters_by_type[worker_type_id]
        except KeyError as exc:
            raise KeyError(f"No worker adapter registered for type_id: {worker_type_id}") from exc

    def dispatch_task(self, task: Task) -> TaskResult:
        worker = self.dispatcher.select_worker(task)
        if worker is None:
            return TaskResult(
                task_id=task.task_id,
                worker_id="",
                status="failed",
                summary="No eligible worker found for task.",
                error="no_eligible_worker",
            )

        worker_type = self.worker_registry.get_type(worker.type_id)
        adapter = self.get_adapter(worker_type.type_id)
        return self.runner.run(adapter, worker, task)

    def get_pending_approval_count(self) -> int:
        return len(self.approval_manager.list_pending())

    def build_runtime_snapshot(self) -> dict:
        return {
            "workers": len(self.worker_registry.list_workers()),
            "pending_approvals": self.get_pending_approval_count(),
            "events": len(self.event_log.list_all()),
        }

