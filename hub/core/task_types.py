from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HubTask:
    task_id: str
    kind: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=utc_now)
    status: str = "queued"  # queued, running, done, failed
    result: dict[str, Any] | None = None
    error: str | None = None