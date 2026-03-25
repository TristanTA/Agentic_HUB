from pydantic import BaseModel, Field
from typing import List


class ToolPolicy(BaseModel):
    tool_id: str
    mode: str = Field(default="allow", description="allow, deny, restricted")
    max_calls_per_run: int | None = None
    allowed_targets: List[str] = Field(default_factory=list)
    require_approval: bool = False
    cooldown_seconds: int | None = None
    access_level: str = Field(default="read", description="read, write, execute")
