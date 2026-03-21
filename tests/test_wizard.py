from __future__ import annotations

from control_plane.builder_service import BuilderService
from control_plane.config_editor import ConfigEditor
from control_plane.wizard import TelegramWizardService
from storage.files.repository import FileRepository
from storage.sqlite.db import SQLiteStore


def test_new_agent_wizard_creates_native_internal_agent(repo_copy):
    store = SQLiteStore(repo_copy / "data" / "hub.db")
    builder = BuilderService(repo_copy, ConfigEditor(repo_copy), FileRepository(repo_copy))
    wizard = TelegramWizardService(store, builder)
    session_key = "123:456"

    wizard.start_new_agent(session_key)
    wizard.handle_text(session_key, "researcher")
    wizard.handle_text(session_key, "Finds relevant information quickly")
    wizard.handle_text(session_key, "Cold, concise, analytical")
    wizard.handle_callback(session_key, "wizard:new_agent:exposure:internal_worker")
    wizard.handle_callback(session_key, "wizard:new_agent:execution:native_hub")
    wizard.handle_callback(session_key, "wizard:new_agent:model:echo_model")
    wizard.handle_callback(session_key, "wizard:new_agent:tools:minimal_worker")
    result = wizard.handle_callback(session_key, "wizard:new_agent:skills:general_style")

    assert result is not None
    assert result.final_result is not None
    assert result.final_result["status"] == "created"
    assert (repo_copy / "agents" / "researcher" / "soul.md").exists()


def test_new_agent_wizard_creates_standalone_external_agent(repo_copy):
    store = SQLiteStore(repo_copy / "data" / "hub.db")
    builder = BuilderService(repo_copy, ConfigEditor(repo_copy), FileRepository(repo_copy))
    wizard = TelegramWizardService(store, builder)
    session_key = "123:456"

    wizard.start_new_agent(session_key)
    wizard.handle_text(session_key, "rowan")
    wizard.handle_text(session_key, "Wedding planning helper")
    wizard.handle_text(session_key, "Direct, organized")
    wizard.handle_callback(session_key, "wizard:new_agent:exposure:standalone_telegram")
    wizard.handle_callback(session_key, "wizard:new_agent:execution:external_adapter")
    wizard.handle_callback(session_key, "wizard:new_agent:adapter:telegram_bot")
    wizard.handle_text(session_key, "ROWAN_BOT_TOKEN")
    result = wizard.handle_text(session_key, "123456")

    assert result is not None
    assert result.final_result is not None
    assert result.final_result["status"] == "created"
    local_config = (repo_copy / "agents" / "rowan" / "config.yaml").read_text(encoding="utf-8")
    assert "standalone_telegram" in local_config
