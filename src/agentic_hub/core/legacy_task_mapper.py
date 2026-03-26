from __future__ import annotations

from agentic_hub.models.task import Task as RuntimeTask
from agentic_hub.models.task_result import TaskResult as RuntimeTaskResult
from agentic_hub.core.legacy_tasks import Task as LegacyTask
from agentic_hub.core.legacy_tasks import TaskResult as LegacyTaskResult


def legacy_task_to_runtime_task(task: LegacyTask) -> RuntimeTask:
    required_tool_ids = list(task.payload.get("required_tool_ids", []))
    required_memory_types = list(task.payload.get("required_memory_types", []))

    return RuntimeTask(
        task_id=task.id,
        kind=task.handler_name,
        payload=dict(task.payload),
        status="queued",
        priority=task.priority,
        created_at=task.last_run_at or task.next_run_at,
        next_run_at=task.next_run_at,
        required_tool_ids=required_tool_ids,
        required_memory_types=required_memory_types,
        approval_required=bool(task.payload.get("approval_required", False)),
        target_worker_id=task.payload.get("target_worker_id"),
        target_role_id=task.payload.get("target_role_id"),
        session_id=task.payload.get("session_id"),
        run_group_id=task.payload.get("run_group_id"),
        correlation_id=task.payload.get("correlation_id"),
    )


def runtime_result_to_legacy_result(result: RuntimeTaskResult) -> LegacyTaskResult:
    status = "success" if result.status == "done" else "failed"
    output = {
        "summary": result.summary,
        "output_payload": result.output_payload,
        "artifact_refs": result.artifact_refs,
        "follow_up_tasks": result.follow_up_tasks,
    }

    return LegacyTaskResult(
        task_id=result.task_id,
        status=status,
        output=output,
        error=result.error,
    )


