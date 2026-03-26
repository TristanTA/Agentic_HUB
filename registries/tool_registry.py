from __future__ import annotations

from typing import Dict, Iterable

from schemas.tool_definition import ToolDefinition


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.tool_id in self._tools:
            raise ValueError(f"Tool already registered: {tool.tool_id}")
        self._tools[tool.tool_id] = tool

    def upsert(self, tool: ToolDefinition) -> None:
        self._tools[tool.tool_id] = tool

    def get(self, tool_id: str) -> ToolDefinition:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"Unknown tool_id: {tool_id}") from exc

    def list_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def ids(self) -> Iterable[str]:
        return self._tools.keys()

    def has(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def clear(self) -> None:
        self._tools.clear()
