from __future__ import annotations

import traceback
from typing import Callable

from hub.worker_adapter import WorkerAdapter
from schemas.task import Task
from schemas.task_result import TaskResult
from schemas.worker_instance import WorkerInstance


class LegacyHandlerAdapter(WorkerAdapter):
    """
    Adapter that lets the new worker runtime call old deterministic handlers.

    Resolution order:
    1. task.payload["handler_name"]
    2. task.kind
    """

    def __init__(self, handlers: dict[str, Callable], logger) -> None:
        self.handlers = handlers
        self.logger = logger

    def run(self, worker: WorkerInstance, task: Task) -> TaskResult:
        handler_name = str(task.payload.get("handler_name") or task.kind)

        try:
            handler = self.handlers[handler_name]
        except KeyError as exc:
            return TaskResult(
                task_id=task.task_id,
                worker_id=worker.worker_id,
                status="failed",
                summary=f"Missing handler: {handler_name}",
                error=str(exc),
            )

        try:
            output = handler(task.payload)
            return TaskResult(
                task_id=task.task_id,
                worker_id=worker.worker_id,
                status="done",
                summary=f"Handler {handler_name} completed.",
                output_payload={"result": output},
            )
        except Exception:
            err = traceback.format_exc()
            self.logger.error("Worker task failed: %s\n%s", handler_name, err)
            return TaskResult(
                task_id=task.task_id,
                worker_id=worker.worker_id,
                status="failed",
                summary=f"Handler {handler_name} failed.",
                error=err,
            )
