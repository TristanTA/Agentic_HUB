from __future__ import annotations

from hub.inputs.normalize import normalize_telegram_payload
from hub.main import build_runtime
from shared.schemas import TargetType


def test_markdown_task_and_result_are_written(repo_copy):
    runtime = build_runtime(repo_copy)
    runtime.bundle.routes[0].target_type = TargetType.WORKFLOW
    runtime.bundle.routes[0].target_id = "planner_to_general"
    result = runtime.process_event(normalize_telegram_payload({"text": "plan a roadmap"}))
    task_files = list((repo_copy / "workspace" / "agent_tasks").glob("*.md"))
    result_files = list((repo_copy / "workspace" / "agent_tasks").glob("*.result.md"))
    assert result["output_text"]
    assert task_files
    assert result_files
