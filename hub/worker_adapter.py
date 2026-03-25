from __future__ import annotations

from typing import Protocol

from schemas.task import Task
from schemas.task_result import TaskResult
from schemas.worker_instance import WorkerInstance


class WorkerAdapter(Protocol):
    def run(self, worker: WorkerInstance, task: Task) -> TaskResult:
        ...
