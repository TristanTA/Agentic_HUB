from __future__ import annotations

from control_plane.builder_service import BuilderService
from control_plane.config_editor import ConfigEditor
from control_plane.wizard import TelegramWizardService
from storage.files.repository import FileRepository
from storage.sqlite.db import SQLiteStore


def test_new_agent_wizard_creates_agent(repo_copy):
    store = SQLiteStore(repo_copy / "data" / "hub.db")
    builder = BuilderService(repo_copy, ConfigEditor(repo_copy), FileRepository(repo_copy))
    wizard = TelegramWizardService(store, builder)
    session_key = "123:456"

    wizard.start_new_agent(session_key)
    wizard.handle_text(session_key, "researcher")
    wizard.handle_text(session_key, "Finds relevant information quickly")
    wizard.handle_text(session_key, "Cold, concise, analytical")
    wizard.handle_callback(session_key, "wizard:new_agent:model:echo_model")
    wizard.handle_callback(session_key, "wizard:new_agent:tools:workspace_only")
    result = wizard.handle_callback(session_key, "wizard:new_agent:skills:general_style")

    assert result is not None
    assert result.final_result is not None
    assert result.final_result["status"] == "created"
    assert (repo_copy / "agents" / "researcher" / "soul.md").exists()
