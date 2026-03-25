import time
import uuid
from datetime import timedelta

from hub.config import DEAD_TASKS_FILE, HEARTBEAT_SECONDS, STATE_FILE, TASKS_FILE
from hub.dead_task_store import DeadTaskStore
from hub.executor import Executor
from hub.logger import get_logger
from hub.state import HubState
from hub.task_store import TaskStore
from hub.tasks import DeadTaskRecord, Task, TaskResult, utc_now
import hub.handlers as handlers


class Hub:
    def __init__(self):
        self.logger = get_logger()
        self.state = HubState()

        self.executor = Executor(
            handlers={
                "startup_task": handlers.startup_task,
                "interval_task": handlers.interval_task,
            },
            logger=self.logger,
        )

        self.task_store = TaskStore(TASKS_FILE)
        self.dead_task_store = DeadTaskStore(DEAD_TASKS_FILE)
        self.tasks = self.task_store.load()
        self.ran_startup_ids: set[str] = set()

        if not self.tasks:
            self.tasks = self._default_tasks()
            self.task_store.save(self.tasks)

    def _default_tasks(self) -> list[Task]:
        now = utc_now()
        return [
            Task(
                id=str(uuid.uuid4()),
                name="Startup Task",
                handler_name="startup_task",
                priority=1,
                trigger="startup",
            ),
            Task(
                id=str(uuid.uuid4()),
                name="Interval Task",
                handler_name="interval_task",
                priority=2,
                trigger="interval",
                interval_seconds=30,
                next_run_at=now,
                max_retries=3,
                retry_delay_seconds=10,
            ),
        ]

    def run(self):
        self.state.status = "running"
        self.state.save(STATE_FILE)
        self.logger.info("Hub running")

        while not self.state.stop_requested:
            self.heartbeat()

            task = self.get_next_task()
            if task:
                result = self.executor.execute(task)
                self.handle_result(task, result)

            time.sleep(HEARTBEAT_SECONDS)

        self.shutdown()

    def heartbeat(self):
        self.logger.info("Heartbeat")

    def get_next_task(self) -> Task | None:
        now = utc_now()
        due = [t for t in self.tasks if t.is_due(now, self.ran_startup_ids)]
        due.sort(key=lambda t: (t.priority, t.next_run_at or now))
        return due[0] if due else None

    def handle_result(self, task: Task, result: TaskResult):
        now = utc_now()

        task.last_run_at = now
        task.last_status = result.status
        task.last_error = result.error

        if result.status == "success":
            task.retry_count = 0

            if task.trigger == "startup":
                self.ran_startup_ids.add(task.id)

            elif task.trigger == "interval":
                if task.interval_seconds is not None:
                    task.next_run_at = now + timedelta(seconds=task.interval_seconds)

            elif task.trigger == "once":
                task.enabled = False

            self.task_store.save(self.tasks)
            self.logger.info("Task %s -> success", task.name)
            return

        self._handle_task_failure(task, result, now)

    def _handle_task_failure(self, task: Task, result: TaskResult, now):
        task.retry_count += 1

        if task.retry_count <= task.max_retries:
            delay_seconds = task.retry_delay_seconds * (2 ** (task.retry_count - 1))
            task.next_run_at = now + timedelta(seconds=delay_seconds)

            self.task_store.save(self.tasks)
            self.logger.warning(
                "Task %s failed (%s/%s). Retrying in %ss",
                task.name,
                task.retry_count,
                task.max_retries,
                delay_seconds,
            )
            return

        dead_record = DeadTaskRecord(
            task_data=task.to_dict(),
            failed_at=now,
            reason=result.error or "Task exceeded max retries",
            retry_count=task.retry_count,
        )
        self.dead_task_store.append(dead_record)

        self.tasks = [t for t in self.tasks if t.id != task.id]
        self.task_store.save(self.tasks)

        self.logger.error(
            "Task %s exceeded max retries and was moved to dead_tasks.json",
            task.name,
        )

    def request_stop(self):
        self.state.stop_requested = True

    def shutdown(self):
        self.state.status = "stopped"
        self.state.save(STATE_FILE)
        self.task_store.save(self.tasks)
        self.logger.info("Hub stopped")