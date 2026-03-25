from pydantic import BaseModel, Field
from typing import Any, List


class MemoryPolicy(BaseModel):
    policy_id: str
    allowed_memory_types: List[str] = Field(default_factory=list)
    retrieval_limits: dict[str, Any] = Field(default_factory=dict)
    allowed_tags: List[str] = Field(default_factory=list)
    write_permissions: dict[str, bool] = Field(
        default_factory=lambda: {
            "working": True,
            "episodic": True,
            "semantic": False,
        }
    )
    promotion_rules_ref: str | None = None
