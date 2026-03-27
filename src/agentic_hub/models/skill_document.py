from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


SkillStatus = Literal["draft", "approved", "rejected", "archived"]


class SkillDocument(BaseModel):
    skill_id: str
    title: str
    summary: str
    content: str
    body_path: str
    evidence_sources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: SkillStatus = "draft"
    usage_count: int = 0
    demand_count: int = 0
    target_loadout_ids: list[str] = Field(default_factory=list)
    gap_key: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_reviewed_at: datetime | None = None
