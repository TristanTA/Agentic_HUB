from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from agentic_hub.models.approval import ApprovalRequest


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalManager:
    def __init__(self) -> None:
        self._requests: Dict[str, ApprovalRequest] = {}
        self._task_to_approval: Dict[str, str] = {}

    def create_request(self, request: ApprovalRequest) -> None:
        if request.approval_id in self._requests:
            raise ValueError(f"Approval already exists: {request.approval_id}")
        self._requests[request.approval_id] = request
        self._task_to_approval[request.task_id] = request.approval_id

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
        return req

    def reject(self, approval_id: str, approver_id: str, note: str | None = None) -> ApprovalRequest:
        req = self.get_request(approval_id)
        req.status = "rejected"
        req.approver_id = approver_id
        req.response_note = note
        req.responded_at = utc_now()
        return req

    def list_pending(self) -> list[ApprovalRequest]:
        return [req for req in self._requests.values() if req.status == "pending"]

