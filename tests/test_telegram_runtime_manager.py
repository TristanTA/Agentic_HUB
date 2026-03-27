from pathlib import Path

import pytest

from agentic_hub.catalog.catalog_manager import CatalogManager
from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.core.service_manager import ServiceManager
from agentic_hub.core.telegram_runtime_manager import TelegramRuntimeManager


class DummyHub:
    pass


def build_manager(tmp_path: Path) -> TelegramRuntimeManager:
    repo_root = Path(__file__).resolve().parents[1]
    worker_registry = WorkerRegistry()
    tool_registry = ToolRegistry()
    catalog_manager = CatalogManager(
        worker_registry,
        tool_registry,
        packs_dir=repo_root / "content" / "packs",
        overrides_dir=tmp_path / "runtime" / "catalog_overrides",
    )
    catalog_manager.reload_catalog()

    manager = TelegramRuntimeManager(
        hub=DummyHub(),
        worker_registry=worker_registry,
        service_manager=ServiceManager(),
        runtime_dir=tmp_path / "runtime",
        env_path=tmp_path / ".env",
    )
    manager.conversation_agent.generate_reply = lambda worker, messages, user_message, channel_type: f"{worker.worker_id}:{user_message}"  # type: ignore[method-assign]
    return manager


def test_attach_managed_bot_rejects_non_managed_workers(tmp_path, monkeypatch) -> None:
    manager = build_manager(tmp_path)
    monkeypatch.setattr("agentic_hub.services.telegram.client.TelegramClient.get_me", lambda self: {"ok": True, "result": {"username": "aria_bot", "first_name": "Aria"}})
    monkeypatch.setattr("agentic_hub.services.telegram.service.TelegramPollingService.start", lambda self: setattr(self, "_running", True))

    with pytest.raises(ValueError):
        manager.attach_managed_bot("aria", "token-1")


def test_attach_managed_bot_succeeds_for_managed_worker(tmp_path, monkeypatch) -> None:
    manager = build_manager(tmp_path)
    worker = manager.worker_registry.get_worker("aria")
    worker.interface_mode = "managed"
    monkeypatch.setattr("agentic_hub.services.telegram.client.TelegramClient.get_me", lambda self: {"ok": True, "result": {"username": "aria_bot", "first_name": "Aria"}})
    monkeypatch.setattr("agentic_hub.services.telegram.service.TelegramPollingService.start", lambda self: setattr(self, "_running", True))

    record = manager.attach_managed_bot("aria", "token-1")

    assert record.bot_username == "aria_bot"
    assert "TELEGRAM_WORKER_BOT_ARIA_TOKEN=token-1" in manager.env_path.read_text(encoding="utf-8")
    assert manager.list_managed_bots()[0].worker_id == "aria"


def test_hybrid_session_reply_persists_history(tmp_path) -> None:
    manager = build_manager(tmp_path)

    session = manager.open_hybrid_session("aria", chat_id=100, user_id=200)
    reply = manager.send_hybrid_message(chat_id=100, user_id=200, worker_id=None, text="hello")

    assert session.worker_id == "aria"
    assert reply == "aria:hello"
    stored = manager.list_hybrid_sessions(100)[0]
    assert len(stored.messages) == 2


def test_internal_worker_cannot_open_hybrid_session(tmp_path) -> None:
    manager = build_manager(tmp_path)

    with pytest.raises(ValueError):
        manager.open_hybrid_session("atlas", chat_id=100, user_id=200)
