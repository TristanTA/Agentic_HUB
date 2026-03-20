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
