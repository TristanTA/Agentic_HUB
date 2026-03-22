from __future__ import annotations

import yaml

from control_plane.commands import parse_management_command
from control_plane.service import ControlPlaneService
from hub.main import build_runtime


def test_parse_management_command_supports_args_and_options():
    command = parse_management_command(
        '/new_agent researcher --purpose "Finds relevant information quickly" --model echo_model --skills general_style'
    )

    assert command is not None
    assert command.name == "new_agent"
    assert command.args == ["researcher"]
    assert command.options["purpose"] == "Finds relevant information quickly"
    assert command.options["model"] == "echo_model"
    assert command.options["skills"] == "general_style"


def test_new_agent_command_scaffolds_files_and_registers_agent(repo_copy):
    service = ControlPlaneService(repo_copy)

    result = service.handle_management_command(
        '/new_agent researcher --purpose "Finds relevant information quickly" --model echo_model'
    )

    assert result["status"] == "created"
    assert result["agent_id"] == "researcher"
    assert (repo_copy / "agents" / "researcher" / "soul.md").exists()
    assert (repo_copy / "agents" / "researcher" / "config.yaml").exists()
    assert (repo_copy / "prompts" / "agents" / "researcher.md").exists()

    payload = yaml.safe_load((repo_copy / "configs" / "agents.yaml").read_text(encoding="utf-8"))
    created = next(item for item in payload["agents"] if item["id"] == "researcher")
    assert created["preferred_model"] == "echo_model"
    assert created["allowed_tools"] == ["workspace_note"]
    assert created["skill_ids"] == ["general_style"]


def test_new_agent_command_returns_help_when_required_fields_are_missing(repo_copy):
    service = ControlPlaneService(repo_copy)

    result = service.handle_management_command("/new_agent researcher")

    assert result["status"] == "needs_input"
    assert result["command"] == "new_agent"
    assert "/new_agent <agent_id>" in result["message"]


def test_attach_agent_command_creates_external_profile(repo_copy):
    service = ControlPlaneService(repo_copy)

    result = service.handle_management_command(
        '/attach_agent rowan --purpose "Wedding planning helper" --adapter_type telegram_bot --bot_token_env ROWAN_BOT_TOKEN --chat_id 12345 --exposure_mode hub_addressable'
    )

    assert result["status"] == "created"
    local_config = (repo_copy / "agents" / "rowan" / "config.yaml").read_text(encoding="utf-8")
    assert "external_adapter" in local_config
    assert "telegram_bot" in local_config


def test_delegate_command_dispatches_structured_task(repo_copy):
    runtime = build_runtime(repo_copy)
    service = ControlPlaneService(repo_copy)
    service.bind_runtime(runtime)

    result = service.handle_management_command('/delegate --assigned_to planner_agent --goal "Plan migration steps"')

    assert result["status"] == "ok"
    assert result["task"]["assigned_to"] == "planner_agent"
    assert result["task"]["status"] in {"completed", "failed", "running"}


def test_vanta_docs_command_returns_self_model(repo_copy):
    service = ControlPlaneService(repo_copy)
    result = service.handle_management_command("/vanta_docs")

    assert result["status"] == "ok"
    assert result["self"]["agent_id"] == "vanta_manager"


def test_agent_command_returns_agent_summary(repo_copy):
    service = ControlPlaneService(repo_copy)
    result = service.handle_management_command("/agent vanta_manager")

    assert result["status"] == "ok"
    assert result["agent"]["id"] == "vanta_manager"


def test_scorecards_command_returns_agent_scorecards(repo_copy):
    service = ControlPlaneService(repo_copy)
    result = service.handle_management_command("/scorecards")

    assert result["status"] == "ok"
    assert any(item["agent_id"] == "vanta_manager" for item in result["scorecards"])


def test_vanta_focus_command_returns_target(repo_copy):
    service = ControlPlaneService(repo_copy)
    result = service.handle_management_command("/vanta_focus")

    assert result["status"] == "ok"
    assert "target" in result
