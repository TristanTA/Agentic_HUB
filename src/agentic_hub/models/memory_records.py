from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Any, List


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunEpisode(BaseModel):
    run_id: str
    worker_id: str
    task_id: str
    objective: str
    actions_summary: str = ""
    outcome: str = ""
    artifacts: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=utc_now)


class SessionEpisode(BaseModel):
    session_id: str
    participants: List[str] = Field(default_factory=list)
    goals: List[str] = Field(default_factory=list)
    key_events: List[str] = Field(default_factory=list)
    unresolved_items: List[str] = Field(default_factory=list)
    summary: str = ""
    updated_at: datetime = Field(default_factory=utc_now)


class SemanticFact(BaseModel):
    key: str
    value: Any
    status: str = Field(default="active", description="active, superseded, deprecated")
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    confidence: float = 1.0
    source_episode_id: str | None = None
    last_updated: datetime = Field(default_factory=utc_now)
