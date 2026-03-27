import os
import time
import uuid
from datetime import timedelta
from pathlib import Path

import agentic_hub.core.handlers as handlers
from agentic_hub.catalog.catalog_manager import CatalogManager
from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.core.command_handlers import CommandHandlers
from agentic_hub.core.dead_task_store import DeadTaskStore
from agentic_hub.core.event_log import EventLog
from agentic_hub.core.executor import Executor
from agentic_hub.core.hub_state import HubState
from agentic_hub.core.legacy_tasks import DeadTaskRecord, Task, TaskResult, utc_now
from agentic_hub.core.logging import get_logger
from agentic_hub.core.memory_manager import MemoryManager
from agentic_hub.core.runtime_config import (
    CATALOG_RUNTIME_DIR,
    CATALOG_SEED_DIR,
    DEAD_TASKS_FILE,
    ENV_FILE,
    EVENTS_FILE,
    HEARTBEAT_SECONDS,
    RUNTIME_DIR,
    STATE_FILE,
    TASKS_FILE,
)
from agentic_hub.core.skill_library import SkillLibrary
from agentic_hub.core.service_manager import ServiceManager
from agentic_hub.core.task_store import TaskStore
from agentic_hub.core.task_types import HubTask
from agentic_hub.core.telegram_runtime_manager import TelegramRuntimeManager
from agentic_hub.core.vanta_admin import VantaAdminAgent
from agentic_hub.services.telegram.service import TelegramPollingService


class Hub:
    def __init__(self, *, register_services: bool = True):
        self.project_root = Path(__file__).resolve().parents[3]
        self.logger = get_logger()
        self.state = HubState()
        self.service_manager = ServiceManager()
        self.tool_registry = ToolRegistry()
        self.worker_registry = WorkerRegistry()
        self.event_log = EventLog(EVENTS_FILE)
        self.memory_manager = MemoryManager()
        self.catalog_manager = CatalogManager(
            self.worker_registry,
            self.tool_registry,
            packs_dir=CATALOG_SEED_DIR,
            overrides_dir=CATALOG_RUNTIME_DIR,
        )
        self.catalog_manager.reload_catalog()
        self.skill_library = SkillLibrary(
            runtime_dir=RUNTIME_DIR,
            repo_root=self.project_root,
            catalog_manager=self.catalog_manager,
        )
        self.telegram_runtime_manager = TelegramRuntimeManager(
            hub=self,
            worker_registry=self.worker_registry,
            service_manager=self.service_manager,
            runtime_dir=RUNTIME_DIR,
            env_path=ENV_FILE,
            skill_library=self.skill_library,
        )
        if register_services:
            self._register_services()
            self.telegram_runtime_manager.register_persisted_managed_bots()

        self.executor = Executor(
            handlers={
                "startup_task": handlers.startup_task,
                "start_service_task": lambda payload: handlers.start_service_task(payload, hub=self),
                "interval_task": handlers.interval_task,
            },
            logger=self.logger,
        )
        self.command_handlers = CommandHandlers(self)
        self.vanta_admin = VantaAdminAgent(self)
        self.task_store = TaskStore(TASKS_FILE)
        self.dead_task_store = DeadTaskStore(DEAD_TASKS_FILE)
        self.tasks = self.task_store.load()
        self.ran_startup_ids: set[str] = set()

        if not self.tasks:
            self.tasks = self._default_tasks()
            self.task_store.save(self.tasks)

    def _register_services(self) -> None:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        allowed_raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
        allowed_user_ids: set[int] = set()
        for raw_value in allowed_raw.split(","):
            value = raw_value.strip()
            if not value:
                continue
            try:
                allowed_user_ids.add(int(value))
            except ValueError:
                self.logger.warning("Ignoring invalid TELEGRAM_ALLOWED_USER_IDS entry: %s", value)

        if not bot_token:
            self.logger.warning("TELEGRAM_BOT_TOKEN not set; telegram service not registered")
            return

        telegram = TelegramPollingService(
            hub=self,
            bot_token=bot_token,
            allowed_user_ids=allowed_user_ids,
        )
        self.service_manager.register(
            "telegram",
            telegram,
            metadata={"transport": "telegram", "mode": "control"},
        )
        self.logger.info("Registered service: telegram")

    def _default_tasks(self) -> list[Task]:
        now = utc_now()
        tasks = [
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
                priority=3,
                trigger="interval",
                interval_seconds=30,
                next_run_at=now,
                max_retries=3,
                retry_delay_seconds=10,
            ),
        ]

        if "telegram" in self.service_manager._services:
            tasks.insert(
                1,
                Task(
                    id=str(uuid.uuid4()),
                    name="Start Telegram Service",
                    handler_name="start_service_task",
                    priority=2,
                    trigger="startup",
                    payload={"service_name": "telegram"},
                    max_retries=3,
                    retry_delay_seconds=10,
                ),
            )

        return tasks

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
            elif task.trigger == "interval" and task.interval_seconds is not None:
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
        self.logger.error("Task %s exceeded max retries and was moved to dead_tasks.json", task.name)

    def submit_and_run_task(self, task: HubTask) -> dict:
        command = task.payload["command"]
        if command.strip().startswith("/"):
            text = self.command_handlers.handle(command, task.payload)
        else:
            text = self.vanta_admin.handle_message(command, task.payload)
        return {"text": text}

    def handle_managed_message(self, *, worker_id: str, text: str, payload: dict) -> str:
        return self.telegram_runtime_manager.handle_managed_message(
            worker_id=worker_id,
            chat_id=int(payload["chat_id"]),
            user_id=payload.get("user_id"),
            text=text,
        )

    def request_stop(self):
        self.state.stop_requested = True

    def shutdown(self):
        for service_name in list(self.service_manager._services.keys()):
            try:
                self.service_manager.stop(service_name)
            except Exception as exc:
                self.logger.error("Failed to stop service %s: %s", service_name, exc)

        self.state.status = "stopped"
        self.state.save(STATE_FILE)
        self.task_store.save(self.tasks)
        self.logger.info("Hub stopped")
