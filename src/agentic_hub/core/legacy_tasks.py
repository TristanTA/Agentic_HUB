from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def dt_to_str(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def str_to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class Task:
    id: str
    name: str
    handler_name: str

    priority: int = 3
    enabled: bool = True

    trigger: str = "manual"  # startup | interval | once | manual
    interval_seconds: int | None = None
    next_run_at: datetime | None = None

    last_run_at: datetime | None = None
    last_status: str | None = None
    last_error: str | None = None

    retry_count: int = 0
    max_retries: int = 3
    retry_delay_seconds: int = 10

    payload: dict[str, Any] = field(default_factory=dict)

    def is_due(self, now: datetime, ran_startup_ids: set[str]) -> bool:
        if not self.enabled:
            return False

        if self.trigger == "startup":
            return self.id not in ran_startup_ids

        if self.trigger in {"interval", "once"}:
            return self.next_run_at is not None and now >= self.next_run_at

        return False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["next_run_at"] = dt_to_str(self.next_run_at)
        data["last_run_at"] = dt_to_str(self.last_run_at)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        data = dict(data)
        data["next_run_at"] = str_to_dt(data.get("next_run_at"))
        data["last_run_at"] = str_to_dt(data.get("last_run_at"))
        return cls(**data)


@dataclass
class TaskResult:
    task_id: str
    status: str
    output: Any = None
    error: str | None = None


@dataclass
class DeadTaskRecord:
    task_data: dict[str, Any]
    failed_at: datetime
    reason: str
    retry_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_data": self.task_data,
            "failed_at": dt_to_str(self.failed_at),
            "reason": self.reason,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeadTaskRecord":
        return cls(
            task_data=data["task_data"],
            failed_at=str_to_dt(data["failed_at"]),
            reason=data["reason"],
            retry_count=data["retry_count"],
        )