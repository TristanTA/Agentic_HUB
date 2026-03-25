from pydantic import BaseModel, Field
from typing import List


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
