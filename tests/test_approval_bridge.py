from hub.approval_bridge import ApprovalBridge


def test_parse_approve_command():
    bridge = ApprovalBridge()
    cmd = bridge.parse("/approve abc123 looks good")

    assert cmd is not None
    assert cmd.action == "approve"
    assert cmd.approval_id == "abc123"
    assert cmd.note == "looks good"
