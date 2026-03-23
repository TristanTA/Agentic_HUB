from __future__ import annotations

import os

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


def test_protected_path_rejects_direct_prompt_edit(repo_copy):
    service = ControlPlaneService(repo_copy)

    try:
        service.edit_prompt("configs/models.yaml", "bad")
    except ValueError as exc:
        assert "Protected path" in str(exc)
    else:
        raise AssertionError("Expected protected path edit to fail")


def test_record_incident_persists_to_sqlite_and_tracked_ledger(repo_copy):
    service = ControlPlaneService(repo_copy)

    result = service.record_incident(
        component="hub_runtime",
        summary="Runtime failed while processing a long message",
        likely_cause=f"OPENAI_API_KEY was {os.getenv('OPENAI_API_KEY', 'missing')}",
        failure_type="RuntimeError",
        last_action="process_event",
        details={"api_key": "super-secret", "payload": "x" * 900},
    )

    ledger = (repo_copy / "docs" / "vanta_incidents.md").read_text(encoding="utf-8")
    assert result["summary"].startswith("Runtime failed while processing")
    assert "super-secret" not in ledger
    assert "[redacted]" in ledger or "missing" in ledger
    assert "RuntimeError" in ledger


def test_provider_status_and_latest_incident_commands(repo_copy, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = ControlPlaneService(repo_copy)
    service.record_incident(
        component="model_provider",
        summary="Provider unavailable for Vanta",
        likely_cause="OPENAI_API_KEY is missing.",
        failure_type="ProviderUnavailable",
        last_action="provider_check",
    )

    provider = service.handle_management_command("/provider_status")
    incident = service.handle_management_command("/incident")
    last_failure = service.handle_management_command("/last_failure")

    assert provider["status"] == "ok"
    assert provider["provider_ready"] is False
    assert provider["vanta_state"] == "recovery_only"
    assert incident["status"] == "ok"
    assert incident["incident"]["failure_type"] == "ProviderUnavailable"
    assert last_failure["incident"]["summary"] == incident["incident"]["summary"]


def test_control_logs_target_reads_tracked_incident_ledger(repo_copy):
    service = ControlPlaneService(repo_copy)
    service.record_incident(
        component="control_plane",
        summary="A config validation failed",
        likely_cause="Bad YAML",
        failure_type="ValidationError",
        last_action="reload_config",
    )

    result = service.tail_logs(target="control", lines=10)

    assert result["status"] == "ok"
    assert any("ValidationError" in line for line in result["lines"])
