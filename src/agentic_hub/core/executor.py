import traceback

from agentic_hub.core.legacy_tasks import Task, TaskResult


class Executor:
    def __init__(self, handlers: dict, logger):
        self.handlers = handlers
        self.logger = logger

    def execute(self, task: Task) -> TaskResult:
        try:
            handler = self.handlers[task.handler_name]
            output = handler(task.payload)

            return TaskResult(
                task_id=task.id,
                status="success",
                output=output,
            )
        except Exception:
            err = traceback.format_exc()
            self.logger.error("Task failed: %s\n%s", task.name, err)

            return TaskResult(
                task_id=task.id,
                status="failed",
                error=err,
            )

