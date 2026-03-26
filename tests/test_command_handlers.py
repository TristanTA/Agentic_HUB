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

    assert result.startswith("Hub alive")
    assert "Next:" in result


def test_help_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/help", {})

    assert "/new" in result
    assert "/status" in result
    assert "/tasks" in result
    assert "/workers" in result


def test_unknown_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/wat", {})

    assert result.startswith("Unknown command: /wat")
    assert "Command not recognized." in result


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

    assert "Tasks: 4 total | 1 failed | 0 scheduled" in result


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

    assert result.startswith("Tasks")
    assert "[1] alpha | 1 | done" in result
    assert "[2] beta | 2 | failed" in result


def test_tasks_command_empty() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/tasks", {})

    assert "No tasks available." in result


def test_services_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/services", {})

    assert result.startswith("Services")
    assert "telegram | running | service" in result


def test_runtime_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/runtime", {})

    assert result.startswith("Runtime status")
    assert "worker types: 3" in result


def test_catalog_list_and_create_commands() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    list_result = handlers.handle("/catalog list workers", {})
    assert list_result.startswith("Catalog list")

    create_result = handlers.handle(
        '/catalog create workers {"worker_id":"cmd_worker","name":"Cmd Worker","type_id":"agent_worker","role_id":"operator","loadout_id":"operator_core"}',
        {},
    )
    assert create_result.startswith("Catalog object created")

    listed = handlers.handle("/catalog list workers", {})
    assert "cmd_worker" in listed


def test_catalog_update_command_rejects_invalid_change() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle('/catalog update workers aria {"loadout_id":"missing_loadout"}', {})
    assert result.startswith("Catalog command failed")
    assert "Unknown loadout" in result
