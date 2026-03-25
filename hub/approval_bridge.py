from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApprovalCommand:
    action: str
    approval_id: str
    note: str = ""


class ApprovalBridge:
    def parse(self, message_text: str) -> ApprovalCommand | None:
        text = message_text.strip()
        if text.startswith("/approve "):
            parts = text.split(maxsplit=2)
            approval_id = parts[1]
            note = parts[2] if len(parts) > 2 else ""
            return ApprovalCommand(action="approve", approval_id=approval_id, note=note)

        if text.startswith("/reject "):
            parts = text.split(maxsplit=2)
            approval_id = parts[1]
            note = parts[2] if len(parts) > 2 else ""
            return ApprovalCommand(action="reject", approval_id=approval_id, note=note)

        return None
