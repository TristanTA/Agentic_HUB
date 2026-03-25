from __future__ import annotations

from hub.core.command_handlers import CommandHandlers
from hub.core.service_manager import ServiceManager
from hub.core.task_types import HubTask


class DummyService:
    def is_running(self) -> bool:
        return True

    def status(self) -> dict:
        return {"running": True}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class DummyHub:
    def __init__(self) -> None:
        self.tasks: list[HubTask] = []
        self.service_manager = ServiceManager()
        self.service_manager.register("telegram", DummyService())


def test_ping_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/ping", {})

    assert result == "hub alive"


def test_help_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/help", {})

    assert "/ping" in result
    assert "/status" in result
    assert "/tasks" in result
    assert "/services" in result


def test_unknown_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/wat", {})

    assert result == "unknown command: /wat"


def test_status_command_counts_tasks() -> None:
    hub = DummyHub()
    hub.tasks.extend(
        [
            HubTask(task_id="1", kind="x", payload={}, status="queued"),
            HubTask(task_id="2", kind="x", payload={}, status="running"),
            HubTask(task_id="3", kind="x", payload={}, status="done"),
            HubTask(task_id="4", kind="x", payload={}, status="failed"),
        ]
    )
    handlers = CommandHandlers(hub)

    result = handlers.handle("/status", {})

    assert "queued: 1" in result
    assert "running: 1" in result
    assert "done: 1" in result
    assert "failed: 1" in result


def test_tasks_command_shows_recent_tasks() -> None:
    hub = DummyHub()
    hub.tasks.extend(
        [
            HubTask(task_id="1", kind="alpha", payload={}, status="done"),
            HubTask(task_id="2", kind="beta", payload={}, status="failed"),
        ]
    )
    handlers = CommandHandlers(hub)

    result = handlers.handle("/tasks", {})

    assert "recent tasks:" in result
    assert "1 | alpha | done" in result
    assert "2 | beta | failed" in result


def test_tasks_command_empty() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/tasks", {})

    assert result == "no tasks"


def test_services_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/services", {})

    assert "services:" in result
    assert "telegram | running" in result