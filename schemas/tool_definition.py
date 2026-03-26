from pydantic import BaseModel, Field
from typing import List
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ToolDefinition(BaseModel):
    tool_id: str = Field(..., description="Stable unique tool identifier")
    name: str
    description: str
    capability_tags: List[str] = Field(default_factory=list)
    input_schema_ref: str | None = None
    output_schema_ref: str | None = None
    safety_level: str = Field(default="low", description="low, medium, high")
    implementation_ref: str
    enabled: bool = True
    source: str = Field(default="runtime", description="seed, runtime, package")
    package_id: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)
