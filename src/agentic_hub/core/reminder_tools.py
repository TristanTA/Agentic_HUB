from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from agentic_hub.core.legacy_tasks import Task, utc_now


def schedule_telegram_reminder(
    hub,
    *,
    name: str,
    interval_seconds: int,
    worker_id: str,
    chat_id: int,
    text: str,
) -> dict:
    now = utc_now()
    task = Task(
        id=str(uuid4()),
        name=name,
        handler_name="send_scheduled_telegram_reminder",
        priority=2,
        trigger="interval",
        interval_seconds=interval_seconds,
        next_run_at=now + timedelta(seconds=interval_seconds),
        payload={"worker_id": worker_id, "chat_id": chat_id, "text": text},
    )
    hub.tasks.append(task)
    hub.task_store.save(hub.tasks)
    return {"ok": True, "task_id": task.id, "name": task.name}
