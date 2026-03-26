from hub.approval_manager import ApprovalManager
from hub.approval_response_handler import ApprovalResponseHandler
from schemas.approval import ApprovalRequest


def test_handle_approve_message():
    manager = ApprovalManager()
    manager.create_request(
        ApprovalRequest(
            approval_id="abc123",
            task_id="task1",
            requested_by_worker_id="aria",
            title="Approve Task",
            summary="Approve this task",
        )
    )

    handler = ApprovalResponseHandler(manager)
    text = handler.handle_message("/approve abc123 looks good", approver_id="user1")

    assert text == "approved task1"
    assert manager.get_request("abc123").status == "approved"
