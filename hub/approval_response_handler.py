from __future__ import annotations

from hub.approval_bridge import ApprovalBridge
from hub.approval_manager import ApprovalManager


class ApprovalResponseHandler:
    def __init__(self, approval_manager: ApprovalManager) -> None:
        self.approval_manager = approval_manager
        self.bridge = ApprovalBridge()

    def handle_message(self, text: str, approver_id: str) -> str | None:
        command = self.bridge.parse(text)
        if command is None:
            return None

        if command.action == "approve":
            req = self.approval_manager.approve(
                command.approval_id,
                approver_id=approver_id,
                note=command.note or None,
            )
            return f"approved {req.task_id}"

        if command.action == "reject":
            req = self.approval_manager.reject(
                command.approval_id,
                approver_id=approver_id,
                note=command.note or None,
            )
            return f"rejected {req.task_id}"

        return None
