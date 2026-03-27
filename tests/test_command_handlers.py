from __future__ import annotations

from pathlib import Path
import tempfile

from agentic_hub.catalog.catalog_manager import CatalogManager
from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.core.command_handlers import CommandHandlers
from agentic_hub.core.service_manager import ServiceManager
from agentic_hub.core.task_types import HubTask


class DummyService:
    def is_running(self) -> bool:
        return True

    def status(self) -> dict:
        return {"running": True}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class DummyEvent:
    def __init__(self, event_type: str) -> None:
        from datetime import datetime, timezone

        self.created_at = datetime.now(timezone.utc)
        self.event_type = event_type
        self.task_id = None
        self.worker_id = None


class DummyHub:
    def __init__(self) -> None:
        self.tasks: list[HubTask] = []
        self.service_manager = ServiceManager()
        self.service_manager.register("telegram", DummyService())
        self.state = type("State", (), {"status": "running"})()
        self.event_log = type("EventLog", (), {"list_all": lambda self: [DummyEvent("boot")]})()
        repo_root = Path(__file__).resolve().parents[1]
        runtime_dir = Path(tempfile.mkdtemp())
        self.catalog_manager = CatalogManager(
            WorkerRegistry(),
            ToolRegistry(),
            packs_dir=repo_root / "content" / "packs",
            overrides_dir=runtime_dir / "catalog_overrides",
        )
        self.catalog_manager.reload_catalog()
        self.worker_registry = self.catalog_manager.worker_registry


def test_help_command() -> None:
    handlers = CommandHandlers(DummyHub())

    result = handlers.handle("/help", {})

    assert result.startswith("Vanta control bot")
    assert "/status" in result
    assert "plain-English request" in result


def test_status_command() -> None:
    hub = DummyHub()
    task = HubTask(task_id="1", kind="telegram.command", payload={}, status="queued")
    task.status = "failed"
    hub.tasks.append(task)
    handlers = CommandHandlers(hub)

    result = handlers.handle("/status", {})

    assert result.startswith("Operational status")
    assert "Workers:" in result
    assert "Tasks: 1 total" in result


def test_workers_command() -> None:
    handlers = CommandHandlers(DummyHub())

    result = handlers.handle("/workers", {})

    assert result.startswith("Workers")
    assert "aria" in result


def test_inspect_worker_command() -> None:
    handlers = CommandHandlers(DummyHub())

    result = handlers.handle("/inspect workers aria", {})

    assert result.startswith("workers aria")
    assert "interface_mode:" in result


def test_unknown_command_points_to_vanta() -> None:
    handlers = CommandHandlers(DummyHub())

    result = handlers.handle("/new", {})

    assert result.startswith("Unknown command: /new")
    assert "talk to Vanta in plain English" in result
