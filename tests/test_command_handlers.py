from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from agentic_hub.catalog.catalog_manager import CatalogManager
from agentic_hub.core.command_handlers import CommandHandlers
from agentic_hub.core.service_manager import ServiceManager
from agentic_hub.core.task_types import HubTask
from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.models.telegram_conversation import TelegramConversationSession


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
        self.approval_manager = DummyApprovalManager()
        repo_root = Path(__file__).resolve().parents[1]
        self._runtime_dir = Path(tempfile.mkdtemp())
        self.catalog_manager = CatalogManager(
            WorkerRegistry(),
            ToolRegistry(),
            packs_dir=repo_root / "content" / "packs",
            overrides_dir=self._runtime_dir / "catalog_overrides",
        )
        self.catalog_manager.reload_catalog()
        self.telegram_runtime_manager = DummyTelegramManager()
        self.live_workflow_manager = DummyWorkflowManager()


class DummyTelegramManager:
    def __init__(self) -> None:
        self.bots = []
        self.sessions: dict[int, list[TelegramConversationSession]] = {}

    def list_managed_bots(self):
        return self.bots

    def attach_managed_bot(self, worker_id: str, token: str):
        record = type("Record", (), {"worker_id": worker_id, "bot_username": "aria_bot"})()
        self.bots.append(record)
        return record

    def remove_managed_bot(self, worker_id: str) -> None:
        self.bots = [bot for bot in self.bots if bot.worker_id != worker_id]

    def start_managed_bot(self, worker_id: str) -> dict:
        return {"message": f"{worker_id} started"}

    def stop_managed_bot(self, worker_id: str) -> dict:
        return {"message": f"{worker_id} stopped"}

    def inspect_managed_bot(self, worker_id: str) -> dict:
        return {"worker_id": worker_id, "bot_username": "aria_bot"}

    def open_hybrid_session(self, worker_id: str, chat_id: int, user_id: int | None):
        session = TelegramConversationSession(
            session_id=f"{chat_id}:{worker_id}",
            worker_id=worker_id,
            channel_type="vanta_hybrid",
            chat_id=chat_id,
            user_id=user_id,
        )
        self.sessions.setdefault(chat_id, [])
        self.sessions[chat_id] = [item for item in self.sessions[chat_id] if item.worker_id != worker_id]
        self.sessions[chat_id].append(session)
        return session

    def close_hybrid_session(self, chat_id: int, worker_id: str | None = None):
        sessions = self.sessions.get(chat_id, [])
        closed = []
        for session in sessions:
            if worker_id is None or session.worker_id == worker_id:
                session.active = False
                closed.append(session)
        self.sessions[chat_id] = [session for session in sessions if session.active]
        return closed

    def list_hybrid_sessions(self, chat_id: int):
        return self.sessions.get(chat_id, [])

    def send_hybrid_message(self, *, chat_id: int, user_id: int | None, worker_id: str | None, text: str) -> str:
        if worker_id:
            self.open_hybrid_session(worker_id, chat_id, user_id)
        sessions = self.sessions.get(chat_id, [])
        if not sessions:
            raise ValueError("No active hybrid session. Use /chat-open <worker_id> first.")
        target = sessions[0] if worker_id is None else next(session for session in sessions if session.worker_id == worker_id)
        target.messages.append(type("Msg", (), {"role": "user", "content": text})())
        return f"reply from {target.worker_id}: {text}"


class DummyWorkflowManager:
    def __init__(self) -> None:
        self.items = []

    def start_worker_improvement(self, *, target_worker_id: str, objective: str, requested_by_user_id=None, requested_from_chat_id=None, research_worker_id="nova", operator_worker_id="aria"):
        workflow = type(
            "Workflow",
            (),
            {
                "workflow_id": "wf-1",
                "target_worker_id": target_worker_id,
                "objective": objective,
                "status": "awaiting_approval",
                "approval_id": "approval-1",
            },
        )()
        self.items = [workflow]
        return workflow

    def list_workflows(self):
        return self.items

    def inspect_workflow(self, workflow_id: str):
        return {
            "workflow_id": workflow_id,
            "target_worker_id": "aria",
            "objective": "Improve aria soul",
            "status": "awaiting_approval",
            "approval_id": "approval-1",
            "failure_reason": None,
            "tasks": [{"task_id": "t1", "kind": "research_request", "status": "done", "summary": "done"}],
            "artifacts": [{"artifact_id": "a1", "kind": "research_brief", "title": "brief"}],
        }

    def resume_approved_workflow(self, approval_id: str):
        return {"message": f"Applied change set for {approval_id}"}

    def reject_workflow(self, approval_id: str, note: str | None = None):
        return {"message": f"Rejected {approval_id}"}


class DummyApprovalManager:
    def list_pending(self):
        return []

    def approve(self, approval_id: str, approver_id: str, note: str | None = None):
        return {"approval_id": approval_id, "approver_id": approver_id, "note": note}

    def reject(self, approval_id: str, approver_id: str, note: str | None = None):
        return {"approval_id": approval_id, "approver_id": approver_id, "note": note}


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


def test_new_worker_wizard_uses_plain_inputs() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)
    payload = {"source": "telegram", "chat_id": 1, "user_id": 2}

    result = handlers.handle("/new", payload)
    assert "Choose object type" in result

    result = handlers.handle("1", payload)
    assert "Field 1 of 6: name" in result

    result = handlers.handle("Test Worker", payload)
    assert "Field 2 of 6: type_id" in result
    assert "agent_worker" in result

    handlers.handle("agent_worker", payload)
    handlers.handle("operator", payload)
    handlers.handle("operator_core", payload)
    result = handlers.handle("hybrid", payload)
    assert "Field 6 of 6: enabled" in result
    result = handlers.handle("yes", payload)
    assert result.startswith("Preview changes")
    assert "enabled: True" in result

    result = handlers.handle("confirm", payload)
    assert result.startswith("Created worker")
    assert "test_worker" in result


def test_edit_worker_wizard_uses_plain_inputs() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)
    payload = {"source": "telegram", "chat_id": 7, "user_id": 8}

    result = handlers.handle("/edit", payload)
    assert "Choose object type" in result

    result = handlers.handle("workers", payload)
    assert "Select worker" in result

    result = handlers.handle("aria", payload)
    assert "Editable fields:" in result
    assert "- interface_mode" in result

    result = handlers.handle("enabled", payload)
    assert "Answer yes or no." in result

    result = handlers.handle("no", payload)
    assert result.startswith("Preview changes")
    assert "New value: False" in result

    result = handlers.handle("confirm", payload)
    assert result.startswith("Updated worker")


def test_telegram_attach_bot_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/telegram attachbot aria token-123", {})

    assert result.startswith("Managed bot attached")
    assert "@aria_bot" in result


def test_hybrid_chat_commands() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)
    payload = {"source": "telegram", "chat_id": 10, "user_id": 20}

    result = handlers.handle("/chat-open aria", payload)
    assert result.startswith("Hybrid session opened")

    result = handlers.handle("/chat hello there", payload)
    assert result.startswith("Hybrid reply")
    assert "reply from aria: hello there" in result

    result = handlers.handle("/chat-sessions", payload)
    assert "aria" in result

    result = handlers.handle("/chat-close", payload)
    assert result.startswith("Hybrid sessions closed")


def test_improve_worker_command() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/improve-worker aria improve aria soul", {"user_id": 1, "chat_id": 2})

    assert result.startswith("Worker improvement started")
    assert "wf-1" in result
    assert "approval-1" in result


def test_workflow_commands() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)
    handlers.handle("/improve-worker aria improve aria soul", {"user_id": 1, "chat_id": 2})

    result = handlers.handle("/workflows", {})
    assert result.startswith("Live workflows")
    assert "wf-1" in result

    detail = handlers.handle("/workflow wf-1", {})
    assert detail.startswith("Workflow details")
    assert "research_request" in detail


def test_approve_command_routes_to_workflow_manager() -> None:
    hub = DummyHub()
    handlers = CommandHandlers(hub)

    result = handlers.handle("/approve approval-1 ship it", {"user_id": 99})

    assert result.startswith("Approval recorded")
    assert "Applied change set" in result


