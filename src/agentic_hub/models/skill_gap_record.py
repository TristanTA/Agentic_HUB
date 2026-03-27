from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SkillGapRecord(BaseModel):
    gap_key: str
    examples: list[str] = Field(default_factory=list)
    frequency: int = 0
    explicit_request_count: int = 0
    proposal_count: int = 0
    last_seen_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
