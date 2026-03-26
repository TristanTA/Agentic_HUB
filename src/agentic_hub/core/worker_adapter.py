from __future__ import annotations

from typing import Protocol

from agentic_hub.models.task import Task
from agentic_hub.models.task_result import TaskResult
from agentic_hub.models.worker_instance import WorkerInstance


class WorkerAdapter(Protocol):
    def run(self, worker: WorkerInstance, task: Task) -> TaskResult:
        ...

