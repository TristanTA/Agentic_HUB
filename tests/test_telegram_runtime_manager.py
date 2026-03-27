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
    manager.service_manager.register(
        "telegram",
        type(
            "ControlService",
            (),
            {
                "status": lambda self: {"allowed_user_ids": [200]},
                "is_running": lambda self: True,
                "start": lambda self: None,
                "stop": lambda self: None,
            },
        )(),
    )
    worker = manager.worker_registry.get_worker("aria")
    worker.interface_mode = "managed"
    monkeypatch.setattr("agentic_hub.services.telegram.client.TelegramClient.get_me", lambda self: {"ok": True, "result": {"username": "aria_bot", "first_name": "Aria"}})
    monkeypatch.setattr("agentic_hub.services.telegram.service.TelegramPollingService.start", lambda self: setattr(self, "_running", True))

    record = manager.attach_managed_bot("aria", "token-1")

    assert record.bot_username == "aria_bot"
    assert record.allowed_user_ids == [200]
    assert "TELEGRAM_WORKER_BOT_ARIA_TOKEN=token-1" in manager.env_path.read_text(encoding="utf-8")
    assert manager.list_managed_bots()[0].worker_id == "aria"


def test_managed_session_reply_persists_history(tmp_path) -> None:
    manager = build_manager(tmp_path)
    worker = manager.worker_registry.get_worker("aria")
    worker.interface_mode = "managed"

    reply = manager.handle_managed_message("aria", chat_id=100, user_id=200, text="hello")

    assert reply == "aria:hello"
    stored = manager._find_session("managed_bot", "aria", 100)
    assert stored is not None
    assert len(stored.messages) == 2


def test_managed_sessions_are_scoped_by_topic_thread(tmp_path) -> None:
    manager = build_manager(tmp_path)
    worker = manager.worker_registry.get_worker("aria")
    worker.interface_mode = "managed"

    first = manager.handle_managed_message_in_thread(worker_id="aria", chat_id=100, message_thread_id=1, user_id=200, text="hello one")
    second = manager.handle_managed_message_in_thread(worker_id="aria", chat_id=100, message_thread_id=2, user_id=200, text="hello two")

    assert first == "aria:hello one"
    assert second == "aria:hello two"
    assert manager._find_session("managed_bot", "aria", 100, 1) is not None
    assert manager._find_session("managed_bot", "aria", 100, 2) is not None


def test_allow_managed_chat_persists_for_worker(tmp_path, monkeypatch) -> None:
    manager = build_manager(tmp_path)
    worker = manager.worker_registry.get_worker("aria")
    worker.interface_mode = "managed"
    monkeypatch.setattr("agentic_hub.services.telegram.client.TelegramClient.get_me", lambda self: {"ok": True, "result": {"username": "aria_bot", "first_name": "Aria"}})
    monkeypatch.setattr("agentic_hub.services.telegram.service.TelegramPollingService.start", lambda self: setattr(self, "_running", True))
    manager.attach_managed_bot("aria", "token-1")

    record = manager.allow_managed_chat("aria", 777)

    assert 777 in record.allowed_chat_ids
    assert 777 in manager.get_managed_bot("aria").allowed_chat_ids


def test_internal_worker_cannot_receive_managed_message(tmp_path) -> None:
    manager = build_manager(tmp_path)

    with pytest.raises(ValueError):
        manager.handle_managed_message("atlas", chat_id=100, user_id=200, text="hello")
