from __future__ import annotations

from typing import Protocol

from shared.schemas import AgentContext, ToolResult


class ToolAdapter(Protocol):
    id: str

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        ...
