from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import List


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkerBase(BaseModel):
    worker_id: str
    name: str
    type_id: str
    role_id: str
    loadout_id: str
    status: str = Field(default="enabled", description="enabled, disabled, paused")
    health: str = Field(default="healthy", description="healthy, degraded, failing")
    version: str = "0.1.0"
    assigned_queues: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    tags: List[str] = Field(default_factory=list)
    source: str = Field(default="runtime", description="seed, runtime, package")
    package_id: str | None = None
