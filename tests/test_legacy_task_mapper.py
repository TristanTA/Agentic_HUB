from datetime import timezone, datetime

from hub.legacy_task_mapper import legacy_task_to_runtime_task, runtime_result_to_legacy_result
from hub.tasks import Task as LegacyTask
from schemas.task_result import TaskResult as RuntimeTaskResult


def test_legacy_task_to_runtime_task():
    task = LegacyTask(
        id="1",
        name="Send Task",
        handler_name="send_message",
        payload={
            "required_tool_ids": ["telegram_send_message"],
            "approval_required": True,
            "session_id": "s1",
        },
        next_run_at=datetime.now(timezone.utc),
    )

    runtime_task = legacy_task_to_runtime_task(task)
    assert runtime_task.task_id == "1"
    assert runtime_task.kind == "send_message"
    assert runtime_task.approval_required is True
    assert runtime_task.required_tool_ids == ["telegram_send_message"]


def test_runtime_result_to_legacy_result():
    result = RuntimeTaskResult(
        task_id="1",
        worker_id="w1",
        status="done",
        summary="Completed",
        output_payload={"ok": True},
        artifact_refs=["a1"],
    )
    legacy = runtime_result_to_legacy_result(result)

    assert legacy.status == "success"
    assert legacy.output["summary"] == "Completed"
