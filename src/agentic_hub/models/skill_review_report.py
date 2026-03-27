from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


ReviewRecommendation = Literal["update", "archive", "improve", "keep"]


class SkillReviewItem(BaseModel):
    skill_id: str
    recommendation: ReviewRecommendation
    reason: str


class SkillReviewReport(BaseModel):
    report_id: str
    generated_at: datetime = Field(default_factory=utc_now)
    items: list[SkillReviewItem] = Field(default_factory=list)
