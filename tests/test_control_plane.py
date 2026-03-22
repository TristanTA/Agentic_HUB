from __future__ import annotations

import yaml

from control_plane.service import ControlPlaneService


def test_control_plane_can_toggle_agent(repo_copy):
    service = ControlPlaneService(repo_copy)
    service.disable_agent("planner_agent")
    payload = yaml.safe_load((repo_copy / "configs" / "agents.yaml").read_text(encoding="utf-8"))
    planner = next(item for item in payload["agents"] if item["id"] == "planner_agent")
    assert planner["enabled"] is False


def test_pause_and_resume_update_state(repo_copy):
    service = ControlPlaneService(repo_copy)
    paused = service.pause_hub()
    resumed = service.resume_hub()
    assert paused["state"]["status"] == "paused"
    assert resumed["state"]["status"] == "running"


def test_edit_agent_config_updates_yaml(repo_copy):
    service = ControlPlaneService(repo_copy)
    updated = service.edit_agent_config("planner_agent", {"timeout": 99})
    assert updated["timeout"] == 99


def test_vanta_docs_returns_owned_documents(repo_copy):
    service = ControlPlaneService(repo_copy)
    result = service.vanta_docs()
    assert result["status"] == "ok"
    assert result["self"]["agent_id"] == "vanta_manager"
    assert result["self"]["soul_file"] == "agents/vanta_manager/soul.md"


def test_review_agent_flags_echo_model(repo_copy):
    service = ControlPlaneService(repo_copy)
    result = service.review_agent("planner_agent")
    assert result["status"] == "ok"
    assert "Agent is on the placeholder echo model." in result["concerns"]


def test_edit_prompt_records_change_and_can_be_rolled_back(repo_copy):
    service = ControlPlaneService(repo_copy)
    original = (repo_copy / "prompts" / "agents" / "vanta_manager.md").read_text(encoding="utf-8")

    edit = service.edit_prompt("prompts/agents/vanta_manager.md", "temporary replacement")
    changes = service.vanta_changes(limit=5)
    change_id = changes["changes"][0]["change_id"]

    assert edit["change_id"] == change_id
    assert (repo_copy / "prompts" / "agents" / "vanta_manager.md").read_text(encoding="utf-8") == "temporary replacement"

    rollback = service.rollback_change(change_id)

    assert rollback["status"] == "ok"
    assert (repo_copy / "prompts" / "agents" / "vanta_manager.md").read_text(encoding="utf-8") == original
