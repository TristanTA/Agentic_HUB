from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from hub.catalog_manager import CatalogManager
from hub.core.command_handlers import CommandHandlers
from hub.core.service_manager import ServiceManager
from hub.core.task_types import HubTask
from registries.tool_registry import ToolRegistry
from registries.worker_registry import WorkerRegistry


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
        self.event_log = type("EventLog", (), {"list_all": lambda self: []})()
        self.artifact_store = type("ArtifactStore", (), {"list_for_worker": lambda self, worker_id: []})()
        self.approval_manager = type("ApprovalManager", (), {"list_pending": lambda self: []})()
        repo_root = Path(__file__).resolve().parents[1]
        self._runtime_dir = Path(tempfile.mkdtemp())
        self.catalog_manager = CatalogManager(
            WorkerRegistry(),
            ToolRegistry(),
            seed_dir=repo_root / "hub" / "catalog",
            runtime_dir=self._runtime_dir,
        )
        self.catalog_manager.reload_catalog()


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


def test_runtime_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/runtime", {})

    assert "runtime status" in result
    assert "worker types:" in result


def test_catalog_list_and_create_commands() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    list_result = handlers.handle("/catalog list workers", {})
    assert "workers:" in list_result

    create_result = handlers.handle(
        '/catalog create workers {"worker_id":"cmd_worker","name":"Cmd Worker","type_id":"agent_worker","role_id":"operator","loadout_id":"operator_core"}',
        {},
    )
    assert create_result == "created workers cmd_worker"

    listed = handlers.handle("/catalog list workers", {})
    assert "cmd_worker" in listed


def test_catalog_update_command_rejects_invalid_change() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    with pytest.raises(ValueError):
        handlers.handle('/catalog update workers aria {"loadout_id":"missing_loadout"}', {})
