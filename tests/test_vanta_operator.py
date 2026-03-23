from __future__ import annotations

from hub.main import build_runtime
from hub.runtime.vanta_operator import VantaOperator
from shared.schemas import VantaChangeRecord


def test_vanta_operator_run_once_records_review_and_lesson(repo_copy):
    runtime = build_runtime(repo_copy)
    operator = VantaOperator(runtime)

    result = operator.run_once(trigger="test")

    assert result["trigger"] == "test"
    assert runtime.store.latest_vanta_review() is not None
    assert isinstance(runtime.store.list_vanta_lessons(limit=5), list)


def test_vanta_operator_evaluates_recent_changes(repo_copy):
    runtime = build_runtime(repo_copy)
    control = type("Control", (), {"vanta_focus": lambda self: {"focus_area": "agent_effectiveness", "target": "vanta_manager", "reason": "test"}})()
    setattr(runtime, "control_plane", control)
    runtime.store.record_vanta_change(
        VantaChangeRecord(
            change_id="change-1",
            target_type="prompt",
            target_path="prompts/agents/vanta_manager.md",
            reason="test",
            previous_content="a",
            new_content="b",
        )
    )
    operator = VantaOperator(runtime)

    operator.run_once(trigger="test")

    change = runtime.store.get_vanta_change("change-1")
    assert change is not None
    assert change.evaluated_at is not None
