from __future__ import annotations

from uuid import uuid4

from hub.approval_manager import ApprovalManager
from hub.artifact_store import ArtifactStore
from hub.event_log import EventLog
from hub.policy_resolver import PolicyResolver
from hub.worker_adapter import WorkerAdapter
from schemas.approval import ApprovalRequest
from schemas.artifact import Artifact
from schemas.event import HubEvent
from schemas.task import Task
from schemas.task_result import TaskResult
from schemas.worker_instance import WorkerInstance


class WorkerRunner:
    def __init__(
        self,
        policy_resolver: PolicyResolver,
        approval_manager: ApprovalManager,
        artifact_store: ArtifactStore,
        event_log: EventLog,
    ) -> None:
        self.policy_resolver = policy_resolver
        self.approval_manager = approval_manager
        self.artifact_store = artifact_store
        self.event_log = event_log

    def run(self, adapter: WorkerAdapter, worker: WorkerInstance, task: Task) -> TaskResult:
        self.event_log.append(
            HubEvent(
                event_id=str(uuid4()),
                task_id=task.task_id,
                worker_id=worker.worker_id,
                event_type="task_started",
                payload={"kind": task.kind},
            )
        )

        if self.policy_resolver.task_requires_approval(worker, task):
            approval = ApprovalRequest(
                approval_id=str(uuid4()),
                task_id=task.task_id,
                requested_by_worker_id=worker.worker_id,
                requested_for_worker_id=worker.worker_id,
                title=f"Approve task {task.task_id}",
                summary=f"Task kind: {task.kind}",
                risk_level="medium",
            )
            self.approval_manager.create_request(approval)
            task.status = "waiting_approval"

            artifact = Artifact(
                artifact_id=str(uuid4()),
                task_id=task.task_id,
                worker_id=worker.worker_id,
                kind="approval_request",
                title=approval.title,
                content={
                    "summary": approval.summary,
                    "approval_id": approval.approval_id,
                    "risk_level": approval.risk_level,
                },
            )
            self.artifact_store.save(artifact)

            self.event_log.append(
                HubEvent(
                    event_id=str(uuid4()),
                    task_id=task.task_id,
                    worker_id=worker.worker_id,
                    event_type="approval_requested",
                    payload={"approval_id": approval.approval_id},
                )
            )

            return TaskResult(
                task_id=task.task_id,
                worker_id=worker.worker_id,
                status="needs_approval",
                summary="Task paused pending approval.",
                artifact_refs=[artifact.artifact_id],
            )

        result = adapter.run(worker, task)

        event_type = "task_completed" if result.status == "done" else "task_failed"
        self.event_log.append(
            HubEvent(
                event_id=str(uuid4()),
                task_id=task.task_id,
                worker_id=worker.worker_id,
                event_type=event_type,
                payload={"status": result.status, "summary": result.summary},
            )
        )

        for artifact_ref in result.artifact_refs:
            self.event_log.append(
                HubEvent(
                    event_id=str(uuid4()),
                    task_id=task.task_id,
                    worker_id=worker.worker_id,
                    event_type="artifact_created",
                    payload={"artifact_id": artifact_ref},
                )
            )

        return result
