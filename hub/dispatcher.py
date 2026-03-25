from __future__ import annotations

from typing import List, Optional

from hub.policy_resolver import PolicyResolver
from registries.worker_registry import WorkerRegistry
from schemas.task import Task
from schemas.worker_instance import WorkerInstance


class Dispatcher:
    def __init__(
        self,
        worker_registry: WorkerRegistry,
        policy_resolver: PolicyResolver,
    ) -> None:
        self.worker_registry = worker_registry
        self.policy_resolver = policy_resolver

    def eligible_workers(self, task: Task) -> List[WorkerInstance]:
        workers = self.worker_registry.list_workers()

        if task.target_worker_id:
            workers = [
                worker
                for worker in workers
                if worker.worker_id == task.target_worker_id
            ]

        if task.target_role_id:
            workers = [
                worker
                for worker in workers
                if worker.role_id == task.target_role_id
            ]

        return [
            worker
            for worker in workers
            if self.policy_resolver.worker_can_handle_task(worker, task)
        ]

    def select_worker(self, task: Task) -> Optional[WorkerInstance]:
        eligible = self.eligible_workers(task)
        if not eligible:
            return None

        eligible.sort(
            key=lambda worker: (
                worker.priority_bias,
                worker.health != "healthy",
                worker.worker_id,
            ),
            reverse=True,
        )
        return eligible[0]
