from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from agentic_hub.core.runtime_model_store import RuntimeModelStore
from agentic_hub.models.approval import ApprovalRequest


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalManager:
    def __init__(self, path: Path | None = None) -> None:
        self._requests: Dict[str, ApprovalRequest] = {}
        self._task_to_approval: Dict[str, str] = {}
        self._store = RuntimeModelStore(path, ApprovalRequest) if path is not None else None
        if self._store is not None:
            for request in self._store.load():
                self._requests[request.approval_id] = request
                self._task_to_approval[request.task_id] = request.approval_id

    def create_request(self, request: ApprovalRequest) -> None:
        if request.approval_id in self._requests:
            raise ValueError(f"Approval already exists: {request.approval_id}")
        self._requests[request.approval_id] = request
        self._task_to_approval[request.task_id] = request.approval_id
        self._flush()

    def get_request(self, approval_id: str) -> ApprovalRequest:
        try:
            return self._requests[approval_id]
        except KeyError as exc:
            raise KeyError(f"Unknown approval_id: {approval_id}") from exc

    def get_request_for_task(self, task_id: str) -> Optional[ApprovalRequest]:
        approval_id = self._task_to_approval.get(task_id)
        if not approval_id:
            return None
        return self._requests.get(approval_id)

    def approve(self, approval_id: str, approver_id: str, note: str | None = None) -> ApprovalRequest:
        req = self.get_request(approval_id)
        req.status = "approved"
        req.approver_id = approver_id
        req.response_note = note
        req.responded_at = utc_now()
        self._flush()
        return req

    def reject(self, approval_id: str, approver_id: str, note: str | None = None) -> ApprovalRequest:
        req = self.get_request(approval_id)
        req.status = "rejected"
        req.approver_id = approver_id
        req.response_note = note
        req.responded_at = utc_now()
        self._flush()
        return req

    def list_pending(self) -> list[ApprovalRequest]:
        return [req for req in self._requests.values() if req.status == "pending"]

    def list_all(self) -> list[ApprovalRequest]:
        return list(self._requests.values())

    def _flush(self) -> None:
        if self._store is None:
            return
        self._store.save(list(self._requests.values()))

