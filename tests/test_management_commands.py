from __future__ import annotations

import yaml

from control_plane.commands import parse_management_command
from control_plane.service import ControlPlaneService


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
