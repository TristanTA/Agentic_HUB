from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class CommandHandlers:
    SUPPORTED_COMMANDS = {"/help", "/status", "/workers", "/tasks", "/inspect", "/logs"}

    def __init__(self, hub: Any) -> None:
        self.hub = hub

    def handle(self, command: str, payload: dict[str, Any]) -> str:
        command = command.strip()
        normalized = command.split(maxsplit=1)[0].lower() if command else ""

        if normalized == "/help":
            return self._help()
        if normalized == "/status":
            return self._status()
        if normalized == "/workers":
            return self._workers()
        if normalized == "/tasks":
            return self._tasks()
        if normalized == "/inspect":
            return self._inspect(command)
        if normalized == "/logs":
            return self._logs()

        return self._render(
            f"Unknown command: {normalized or command}",
            [
                "Available commands: /help, /status, /workers, /tasks, /inspect, /logs",
                "For admin changes, just talk to Vanta in plain English.",
            ],
        )

    def _help(self) -> str:
        return self._render(
            "Vanta control bot",
            [
                "Direct commands: /help, /status, /workers, /tasks, /inspect, /logs",
                "For worker creation, loadout updates, and managed bot setup, send a plain-English request.",
            ],
        )

    def _status(self) -> str:
        now = datetime.now(timezone.utc)
        failed = sum(getattr(task, "last_status", None) == "failed" for task in self.hub.tasks)
        scheduled = sum(getattr(task, "trigger", None) in {"interval", "once"} for task in self.hub.tasks)
        overdue = sum(
            getattr(task, "next_run_at", None) is not None and now >= task.next_run_at
            for task in self.hub.tasks
            if getattr(task, "trigger", None) in {"interval", "once"}
        )
        workers = self.hub.worker_registry.list_workers()
        enabled = [worker for worker in workers if worker.enabled]
        managed = [worker for worker in workers if worker.interface_mode == "managed"]
        lines = [
            f"Hub: {self.hub.state.status}",
            f"Workers: {len(workers)} total | {len(enabled)} enabled | {len(managed)} managed",
            f"Tasks: {len(self.hub.tasks)} total | {failed} failed | {scheduled} scheduled",
            f"Services: {len(self.hub.service_manager._services)} registered",
            f"Overdue scheduled tasks: {overdue}",
        ]
        return self._render("Operational status", lines)

    def _workers(self) -> str:
        rows = [
            f"[{idx}] {worker.name} | {worker.worker_id} | {worker.interface_mode} | enabled={worker.enabled}"
            for idx, worker in enumerate(self.hub.worker_registry.list_workers(), start=1)
        ]
        return self._render("Workers", rows or ["No workers available."])

    def _tasks(self) -> str:
        rows = [
            f"[{idx}] {task.name} | {task.id} | {task.last_status or 'queued'} | priority={task.priority}"
            for idx, task in enumerate(self.hub.tasks, start=1)
        ]
        return self._render("Tasks", rows or ["No tasks available."])

    def _inspect(self, command: str) -> str:
        parts = command.split(maxsplit=2)
        if len(parts) < 3:
            return self._render("Inspect command", ["Usage: /inspect <kind> <id>"])

        kind = parts[1].strip().lower()
        object_id = parts[2].strip()
        if kind == "tasks":
            for task in self.hub.tasks:
                if task.id == object_id:
                    return self._render(
                        f"Task {object_id}",
                        [
                            f"name: {task.name}",
                            f"handler: {task.handler_name}",
                            f"status: {task.last_status or 'queued'}",
                            f"trigger: {task.trigger}",
                            f"payload: {task.payload}",
                        ],
                    )
            return self._render("Object not found", [f"No task matched `{object_id}`."])

        kind_map = {
            "workers": "workers",
            "worker": "workers",
            "loadouts": "loadouts",
            "loadout": "loadouts",
            "tools": "tools",
            "tool": "tools",
            "roles": "worker_roles",
            "role": "worker_roles",
            "types": "worker_types",
            "type": "worker_types",
        }
        resolved_kind = kind_map.get(kind)
        if not resolved_kind:
            return self._render("Unknown kind", [f"Unsupported inspect kind `{kind}`."])

        for item in self.hub.catalog_manager.list_objects(resolved_kind):
            identifier = self._catalog_identifier(resolved_kind, item)
            if identifier == object_id:
                payload = item.model_dump(mode="python")
                lines = [f"{key}: {value}" for key, value in payload.items()]
                return self._render(f"{resolved_kind} {identifier}", lines)
        return self._render("Object not found", [f"No {resolved_kind} matched `{object_id}`."])

    def _logs(self) -> str:
        events = self.hub.event_log.list_all()[-10:]
        rows = [
            f"[{idx}] {event.created_at.isoformat()} | {event.event_type} | task={event.task_id or '-'} | worker={event.worker_id or '-'}"
            for idx, event in enumerate(events, start=1)
        ]
        return self._render("Recent logs", rows or ["No recent logs."])

    def _catalog_identifier(self, kind: str, item: Any) -> str:
        fields = {
            "workers": "worker_id",
            "loadouts": "loadout_id",
            "tools": "tool_id",
            "worker_roles": "role_id",
            "worker_types": "type_id",
        }
        return str(getattr(item, fields[kind]))

    def _render(self, title: str, body_lines: list[str]) -> str:
        lines = [title]
        if body_lines:
            lines.append("")
            lines.extend(body_lines)
        return "\n".join(lines)
