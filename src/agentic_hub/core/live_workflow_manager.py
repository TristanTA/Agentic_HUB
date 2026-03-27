from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agentic_hub.core.artifact_store import ArtifactStore
from agentic_hub.core.repo_tools import RepoTools
from agentic_hub.core.runtime_coordinator import RuntimeCoordinator
from agentic_hub.core.runtime_model_store import RuntimeModelStore
from agentic_hub.models.artifact import Artifact
from agentic_hub.models.live_workflow import LiveWorkflow
from agentic_hub.models.task import Task
from agentic_hub.models.task_result import TaskResult
from agentic_hub.models.workflow_task_record import WorkflowTaskRecord


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LiveWorkflowManager:
    def __init__(
        self,
        *,
        runtime_coordinator: RuntimeCoordinator,
        artifact_store: ArtifactStore,
        runtime_dir: Path,
        repo_root: Path,
    ) -> None:
        self.runtime_coordinator = runtime_coordinator
        self.artifact_store = artifact_store
        self.repo_tools = RepoTools(repo_root)
        self.workflow_store = RuntimeModelStore(runtime_dir / "live_workflows.json", LiveWorkflow)
        self.task_store = RuntimeModelStore(runtime_dir / "live_workflow_tasks.json", WorkflowTaskRecord)

    def start_worker_improvement(
        self,
        *,
        target_worker_id: str,
        objective: str,
        requested_by_user_id: str | None = None,
        requested_from_chat_id: str | None = None,
        research_worker_id: str = "nova",
        operator_worker_id: str = "aria",
    ) -> LiveWorkflow:
        workflow = LiveWorkflow(
            workflow_id=str(uuid4()),
            target_worker_id=target_worker_id,
            objective=objective,
            status="researching",
            research_worker_id=research_worker_id,
            operator_worker_id=operator_worker_id,
            requested_by_user_id=requested_by_user_id,
            requested_from_chat_id=requested_from_chat_id,
        )
        self._upsert_workflow(workflow)

        research_task = Task(
            task_id=str(uuid4()),
            kind="research_request",
            target_worker_id=research_worker_id,
            payload={
                "workflow_id": workflow.workflow_id,
                "target_worker_id": target_worker_id,
                "objective": objective,
                "operator_worker_id": operator_worker_id,
            },
        )
        workflow.research_task_id = research_task.task_id
        self._upsert_workflow(workflow)
        self._dispatch_task(workflow, research_task)
        return self.get_workflow(workflow.workflow_id)

    def list_workflows(self) -> list[LiveWorkflow]:
        workflows = self.workflow_store.load()
        workflows.sort(key=lambda workflow: workflow.updated_at, reverse=True)
        return workflows

    def get_workflow(self, workflow_id: str) -> LiveWorkflow:
        for workflow in self.workflow_store.load():
            if workflow.workflow_id == workflow_id:
                return workflow
        raise KeyError(f"Unknown workflow_id: {workflow_id}")

    def get_workflow_for_approval(self, approval_id: str) -> LiveWorkflow | None:
        for workflow in self.workflow_store.load():
            if workflow.approval_id == approval_id:
                return workflow
        return None

    def list_tasks_for_workflow(self, workflow_id: str) -> list[WorkflowTaskRecord]:
        tasks = [task for task in self.task_store.load() if task.workflow_id == workflow_id]
        tasks.sort(key=lambda task: task.created_at)
        return tasks

    def resume_approved_workflow(self, approval_id: str) -> dict[str, str]:
        workflow = self.get_workflow_for_approval(approval_id)
        if workflow is None:
            return {"message": "No live workflow is waiting on that approval."}
        if workflow.change_set_artifact_id is None:
            workflow.status = "failed"
            workflow.failure_reason = "Missing change set artifact."
            self._upsert_workflow(workflow)
            return {"message": "Approval recorded, but no change set was available to apply."}

        change_set = self.artifact_store.get(workflow.change_set_artifact_id).content
        workflow.status = "applying"
        self._upsert_workflow(workflow)

        applied = self._apply_change_set(workflow, change_set)
        verification_commands = list(change_set.get("verification_commands", []))
        verification_task = Task(
            task_id=str(uuid4()),
            kind="verification_request",
            target_worker_id=workflow.operator_worker_id,
            payload={
                "workflow_id": workflow.workflow_id,
                "commands": verification_commands,
                "applied_artifact_id": applied.artifact_id,
            },
        )
        workflow.verification_task_id = verification_task.task_id
        workflow.status = "verifying"
        self._upsert_workflow(workflow)
        self._dispatch_task(workflow, verification_task)
        workflow = self.get_workflow(workflow.workflow_id)
        return {
            "message": f"Applied change set for workflow {workflow.workflow_id}. Current status: {workflow.status}.",
        }

    def reject_workflow(self, approval_id: str, note: str | None = None) -> dict[str, str]:
        workflow = self.get_workflow_for_approval(approval_id)
        if workflow is None:
            return {"message": "No live workflow is waiting on that approval."}
        workflow.status = "rejected"
        workflow.failure_reason = note or "Rejected by user."
        self._upsert_workflow(workflow)
        return {"message": f"Workflow {workflow.workflow_id} was rejected."}

    def inspect_workflow(self, workflow_id: str) -> dict[str, object]:
        workflow = self.get_workflow(workflow_id)
        tasks = self.list_tasks_for_workflow(workflow_id)
        artifacts = [
            artifact
            for artifact in self.artifact_store.list_all()
            if artifact.task_id in {task.task_id for task in tasks}
        ]
        return {
            "workflow_id": workflow.workflow_id,
            "target_worker_id": workflow.target_worker_id,
            "objective": workflow.objective,
            "status": workflow.status,
            "approval_id": workflow.approval_id,
            "failure_reason": workflow.failure_reason,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "kind": task.kind,
                    "status": task.status,
                    "summary": task.summary,
                }
                for task in tasks
            ],
            "artifacts": [
                {
                    "artifact_id": artifact.artifact_id,
                    "kind": artifact.kind,
                    "title": artifact.title,
                }
                for artifact in artifacts
            ],
        }

    def _dispatch_task(self, workflow: LiveWorkflow, task: Task) -> TaskResult:
        record = WorkflowTaskRecord(
            task_id=task.task_id,
            workflow_id=workflow.workflow_id,
            kind=task.kind,
            target_worker_id=task.target_worker_id,
            payload=task.payload,
            status="running",
        )
        self._upsert_task_record(record)
        result = self.runtime_coordinator.dispatch_task(task)
        selected_worker_id = result.worker_id or task.target_worker_id
        record.assigned_worker_id = selected_worker_id
        record.status = result.status
        record.summary = result.summary
        record.artifact_refs = list(result.artifact_refs)
        record.error = result.error
        record.updated_at = utc_now()
        self._upsert_task_record(record)

        workflow.updated_at = utc_now()
        if task.kind == "research_request":
            workflow.research_artifact_id = result.artifact_refs[0] if result.artifact_refs else None
        elif task.kind == "implementation_request":
            if result.output_payload.get("approval_id"):
                workflow.approval_id = str(result.output_payload["approval_id"])
            if result.output_payload.get("change_set_artifact_id"):
                workflow.change_set_artifact_id = str(result.output_payload["change_set_artifact_id"])
            workflow.status = "awaiting_approval"
        elif task.kind == "verification_request":
            workflow.verification_artifact_id = result.artifact_refs[0] if result.artifact_refs else None
            workflow.status = "completed" if result.status == "done" else "failed"
            workflow.failure_reason = result.error
        if result.status == "failed" and task.kind != "verification_request":
            workflow.status = "failed"
            workflow.failure_reason = result.error or result.summary
        self._upsert_workflow(workflow)

        for follow_up in result.follow_up_tasks:
            follow_task = Task(
                task_id=str(uuid4()),
                kind=str(follow_up["kind"]),
                target_worker_id=follow_up.get("target_worker_id"),
                target_role_id=follow_up.get("target_role_id"),
                payload=dict(follow_up.get("payload", {})),
            )
            record.follow_up_task_ids.append(follow_task.task_id)
            if follow_task.kind == "implementation_request":
                workflow.implementation_task_id = follow_task.task_id
            self._upsert_task_record(record)
            self._upsert_workflow(workflow)
            self._dispatch_task(workflow, follow_task)

        return result

    def _apply_change_set(self, workflow: LiveWorkflow, change_set: dict[str, object]) -> Artifact:
        operations = list(change_set.get("file_operations", []))
        applied: list[dict[str, object]] = []
        for operation in operations:
            path = str(operation["path"])
            action = str(operation["action"])
            if action == "delete":
                self.repo_tools.delete_file(path)
                diff = f"Deleted {path}"
            else:
                content = str(operation.get("content", ""))
                diff = self.repo_tools.preview_diff(path, content)
                self.repo_tools.write_file(path, content)
            applied.append(
                {
                    "path": path,
                    "action": action,
                    "reason": operation.get("reason", ""),
                    "diff": diff,
                }
            )

        artifact = Artifact(
            artifact_id=str(uuid4()),
            task_id=workflow.implementation_task_id or workflow.workflow_id,
            worker_id=workflow.operator_worker_id,
            kind="applied_changes",
            title=f"Applied changes for workflow {workflow.workflow_id}",
            content={"operations": applied, "git_diff": self.repo_tools.git_diff()},
        )
        self.artifact_store.save(artifact)
        return artifact

    def _upsert_workflow(self, workflow: LiveWorkflow) -> None:
        workflows = [item for item in self.workflow_store.load() if item.workflow_id != workflow.workflow_id]
        workflow.updated_at = utc_now()
        workflows.append(workflow)
        self.workflow_store.save(workflows)

    def _upsert_task_record(self, record: WorkflowTaskRecord) -> None:
        records = [item for item in self.task_store.load() if item.task_id != record.task_id]
        record.updated_at = utc_now()
        records.append(record)
        self.task_store.save(records)
