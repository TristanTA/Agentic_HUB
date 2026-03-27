from __future__ import annotations

from pathlib import Path

from agentic_hub.core.hub import Hub


def build_hub(tmp_path: Path) -> Hub:
    hub = Hub(register_services=False)
    hub.telegram_runtime_manager.env_path = tmp_path / ".env"
    hub.telegram_runtime_manager.managed_bot_store.path = tmp_path / "managed_telegram_bots.json"
    hub.telegram_runtime_manager.session_store.path = tmp_path / "telegram_conversation_sessions.json"
    hub.catalog_manager.overrides_dir = tmp_path / "catalog_overrides"
    for store in hub.catalog_manager.override_stores.values():
        store.path = tmp_path / "catalog_overrides" / store.path.name
    hub.catalog_manager.reload_catalog()
    return hub


def test_create_internal_worker_in_runtime_overrides(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Create a new internal worker named Banana Helper",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Created worker `banana_helper`" in result
    worker = hub.worker_registry.get_worker("banana_helper")
    assert worker.interface_mode == "internal"
    worker_file = tmp_path / "catalog_overrides" / "workers.json"
    assert worker_file.exists()


def test_managed_worker_request_asks_for_bot_token_then_attaches(tmp_path, monkeypatch) -> None:
    hub = build_hub(tmp_path)
    monkeypatch.setattr("agentic_hub.services.telegram.client.TelegramClient.get_me", lambda self: {"ok": True, "result": {"username": "banana_bot", "first_name": "Banana"}})
    monkeypatch.setattr("agentic_hub.services.telegram.service.TelegramPollingService.start", lambda self: setattr(self, "_running", True))

    question = hub.vanta_admin.handle_message(
        "Create a new managed telegram bot named Banana Bot",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )
    assert "What Telegram bot token" in question

    result = hub.vanta_admin.handle_message(
        "123456:banana_token",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Created worker `banana_bot`" in result
    assert "managed bot inspection succeeded" in result
    managed = hub.telegram_runtime_manager.get_managed_bot("banana_bot")
    assert managed.bot_username == "banana_bot"


def test_code_change_request_requires_approval(tmp_path) -> None:
    hub = build_hub(tmp_path)

    question = hub.vanta_admin.handle_message(
        "Make a new internal agent named Banana Painter that creates images of bananas on command",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )
    assert "What model should this worker use?" in question

    result = hub.vanta_admin.handle_message(
        "Nano-banana",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Approval required before changing executable code" in result
    assert "Banana Painter" not in [worker.name for worker in hub.worker_registry.list_workers()]


def test_plain_language_status_request_maps_to_admin_action(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "show hub status",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Hub `" in result
