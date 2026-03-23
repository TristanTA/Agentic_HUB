from __future__ import annotations

import pytest

from control_plane.service import ControlPlaneService
from hub.inputs.normalize import normalize_telegram_payload
from hub.main import build_runtime


def test_echo_fallback_does_not_dump_langchain_message_repr(repo_copy, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = build_runtime(repo_copy)
    event = normalize_telegram_payload(
        {"message": {"message_id": 1, "chat": {"id": "123"}, "text": "plan a launch roadmap for Aria"}}
    )

    result = runtime.process_event(event)

    assert "HumanMessage(content=" not in result["output_text"]
    assert "plan a launch roadmap for Aria" in result["output_text"]


def test_echo_fallback_extracts_current_input_not_full_prompt(repo_copy, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = build_runtime(repo_copy)
    event = normalize_telegram_payload(
        {
            "message": {
                "message_id": 2,
                "chat": {"id": "321"},
                "text": "Heres the info for aria:\n1. What is Aria?\nA hands-on digital band manager.\nPlease plan the next steps.",
            }
        }
    )

    result = runtime.process_event_for_agent(event, "planner_agent")

    assert result["output_text"].startswith("[echo] Heres the info for aria:")
    assert "# Planner Agent" not in result["output_text"]


def test_vanta_fails_loud_without_real_provider(repo_copy, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = build_runtime(repo_copy)
    control = ControlPlaneService(repo_copy)
    control.bind_runtime(runtime)
    event = normalize_telegram_payload(
        {"message": {"message_id": 3, "chat": {"id": "999"}, "text": "check your status"}}
    )

    with pytest.raises(RuntimeError, match="real model provider"):
        runtime.process_event_for_agent(event, "vanta_manager")
