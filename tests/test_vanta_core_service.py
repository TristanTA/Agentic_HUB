from __future__ import annotations

import json
from datetime import datetime, timezone

from vanta_core.service import VantaCoreService


def test_vanta_core_reports_runtime_down(repo_copy, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    service = VantaCoreService(repo_copy)

    status = service.status()

    assert status["vanta_state"] == "runtime_down"
    assert status["runtime"]["running"] is False


def test_vanta_core_validates_activates_and_explains_agents(repo_copy, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    service = VantaCoreService(repo_copy)
    service.specs.create_draft(
        agent_id="ops_worker",
        purpose="Handle ops tasks.",
        role="operator",
        interface="internal",
        autonomy_level="bounded",
        model_profile="cheap",
        tool_profile="operator",
    )

    validation = service.validate_agent("ops_worker")
    activation = service.activate_agent("ops_worker")
    explanation = service.explain_agent("ops_worker")

    assert validation["status"] == "ok"
    assert activation["status"] == "ok"
    assert explanation["explanation"]["reason"] in {"runtime unavailable", "runtime registry stale"}


def test_vanta_core_records_incident_to_store(repo_copy):
    service = VantaCoreService(repo_copy)
    incident = service.record_incident(
        component="agent_os",
        summary="runtime failed",
        likely_cause="test failure",
        failure_type="RuntimeFailure",
        last_action="restart_runtime",
    )

    latest = service.latest_incident()

    assert incident["summary"] == "runtime failed"
    assert latest["incident"]["failure_type"] == "RuntimeFailure"


def test_vanta_core_resolves_incidents_and_clears_active_status(repo_copy):
    service = VantaCoreService(repo_copy)
    service.record_incident(
        component="vanta_core",
        summary="Telegram polling failure: RuntimeError",
        likely_cause="Unauthorized",
        failure_type="RuntimeError",
        last_action="run_forever",
    )

    assert service.latest_incident()["incident"]["failure_type"] == "RuntimeError"

    resolved = service.resolve_incidents(
        component="vanta_core",
        failure_type="RuntimeError",
        last_action="run_forever",
        resolution_note="Recovered.",
    )

    assert resolved == 1
    assert service.latest_incident()["message"] == "No active incidents."


def test_vanta_core_provider_status_uses_cached_probe(repo_copy, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    probe_path = repo_copy / "data" / "provider_probe.json"
    probe_path.write_text(
        json.dumps({"probe_ok": True, "reason": "cached ok", "checked_at": datetime.now(timezone.utc).isoformat()}),
        encoding="utf-8",
    )
    service = VantaCoreService(repo_copy)
    status = service.provider_status()

    assert status["provider_ready"] is True


def test_vanta_core_plain_text_returns_ops_help(repo_copy):
    service = VantaCoreService(repo_copy)
    result = service.handle_command("hello there")

    assert result["status"] == "help"
    assert "ops mode" in result["message"]
