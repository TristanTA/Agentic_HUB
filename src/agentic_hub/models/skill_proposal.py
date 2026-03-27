from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


ProposalStatus = Literal["pending_approval", "approved", "rejected"]


class SkillProposal(BaseModel):
    proposal_id: str
    skill_id: str
    approval_summary: str
    target_loadout_ids: list[str] = Field(default_factory=list)
    gap_key: str | None = None
    status: ProposalStatus = "pending_approval"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
