from agentic_hub.core.approval_manager import ApprovalManager
from agentic_hub.models.approval import ApprovalRequest


def test_approval_manager_approve_flow():
    manager = ApprovalManager()
    manager.create_request(
        ApprovalRequest(
            approval_id="a1",
            task_id="t1",
            requested_by_worker_id="aria",
            title="Restart service",
            summary="Restart the audit service after repeated failures.",
        )
    )

    result = manager.approve("a1", approver_id="user123", note="Go ahead")

    assert result.status == "approved"
    assert result.approver_id == "user123"
    assert manager.get_request_for_task("t1") is not None

