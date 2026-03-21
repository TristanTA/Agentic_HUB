from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

from hub.adapters.base import AgentAdapter
from hub.outputs.telegram import TelegramOutputAdapter
from shared.schemas import AdapterHealth, AgentTaskRecord, TaskStatus
from storage.sqlite.db import SQLiteStore


class PythonProcessAdapter(AgentAdapter):
    def __init__(self, spec, store: SQLiteStore) -> None:
        super().__init__(spec)
        self.store = store

    def describe(self) -> dict:
        return {"agent_id": self.spec.id, "adapter_type": "python_process", "config": self.spec.adapter_config}

    def health_check(self) -> AdapterHealth:
        command = self.spec.adapter_config.get("command")
        if not command:
            return AdapterHealth(adapter_type="python_process", agent_id=self.spec.id, status="unavailable", details={"error": "missing command"})
        return AdapterHealth(adapter_type="python_process", agent_id=self.spec.id, status="ok")

    def submit_task(self, task: AgentTaskRecord) -> AgentTaskRecord:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        self.store.upsert_agent_task(task)
        command = self.spec.adapter_config.get("command")
        if not command:
            task.status = TaskStatus.FAILED
            task.error = "missing command"
            task.completed_at = datetime.now(timezone.utc)
            self.store.upsert_agent_task(task)
            return task
        completed = subprocess.run(
            command,
            input=json.dumps(task.model_dump(mode="json")),
            capture_output=True,
            text=True,
            shell=isinstance(command, str),
            check=False,
            timeout=int(self.spec.adapter_config.get("timeout", 60)),
        )
        if completed.returncode != 0:
            task.status = TaskStatus.FAILED
            task.error = completed.stderr.strip() or f"process exited {completed.returncode}"
        else:
            stdout = completed.stdout.strip()
            task.status = TaskStatus.COMPLETED
            task.result_summary = stdout[:240]
            task.result_payload = {"stdout": stdout}
        task.completed_at = datetime.now(timezone.utc)
        self.store.upsert_agent_task(task)
        return task

    def get_task(self, task_id: str) -> AgentTaskRecord | None:
        return self.store.get_agent_task(task_id)


class TelegramBotAdapter(AgentAdapter):
    def __init__(self, spec, store: SQLiteStore) -> None:
        super().__init__(spec)
        bot_token_env = self.spec.adapter_config.get("bot_token_env") or self.spec.telegram.get("bot_token_env", "TELEGRAM_BOT_TOKEN")
        self.output = TelegramOutputAdapter(enabled=True, bot_token_env=bot_token_env)
        self.store = store

    def describe(self) -> dict:
        return {"agent_id": self.spec.id, "adapter_type": "telegram_bot", "telegram": self.spec.telegram}

    def health_check(self) -> AdapterHealth:
        bot_token_env = self.spec.adapter_config.get("bot_token_env") or self.spec.telegram.get("bot_token_env")
        status = "ok" if bot_token_env else "unavailable"
        details = {"bot_token_env": bot_token_env or ""}
        return AdapterHealth(adapter_type="telegram_bot", agent_id=self.spec.id, status=status, details=details)

    def submit_task(self, task: AgentTaskRecord) -> AgentTaskRecord:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)
        self.store.upsert_agent_task(task)
        default_chat_id = self.spec.adapter_config.get("chat_id") or self.spec.telegram.get("default_chat_id", "")
        if not default_chat_id:
            task.status = TaskStatus.FAILED
            task.error = "missing chat_id for telegram adapter"
        else:
            delivery = self.output.send({"thread_id": str(default_chat_id), "text": task.input_context})
            task.status = TaskStatus.COMPLETED if delivery.get("status") == "sent" else TaskStatus.FAILED
            task.result_summary = f"sent to telegram agent {self.spec.id}"
            task.result_payload = {"delivery": delivery}
            if task.status == TaskStatus.FAILED:
                task.error = delivery.get("reason", "telegram delivery failed")
        task.completed_at = datetime.now(timezone.utc)
        self.store.upsert_agent_task(task)
        return task

    def get_task(self, task_id: str) -> AgentTaskRecord | None:
        return self.store.get_agent_task(task_id)

    def send_message(self, message: str, thread_id: str = "") -> dict:
        target = thread_id or str(self.spec.adapter_config.get("chat_id") or self.spec.telegram.get("default_chat_id", ""))
        return self.output.send({"thread_id": target, "text": message})
