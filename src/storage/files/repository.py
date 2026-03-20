from __future__ import annotations

import json
from pathlib import Path

from shared.schemas import MarkdownResultFile, MarkdownTaskFile


class FileRepository:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.task_dir = root_dir / "workspace" / "agent_tasks"
        self.task_dir.mkdir(parents=True, exist_ok=True)

    def read_text(self, relative_path: str) -> str:
        return (self.root_dir / relative_path).read_text(encoding="utf-8")

    def write_text(self, relative_path: str, content: str) -> Path:
        path = self.root_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_state(self, relative_path: str, payload: dict) -> Path:
        return self.write_text(relative_path, json.dumps(payload, indent=2))

    def create_markdown_task(self, task: MarkdownTaskFile) -> Path:
        content = "\n".join(
            [
                f"# Task {task.task_id}",
                "",
                f"- source_agent: {task.source_agent}",
                f"- target_agent: {task.target_agent}",
                f"- intent: {task.intent}",
                f"- status: {task.status}",
                "",
                "## Input Context",
                task.input_context,
                "",
            ]
        )
        return self.write_text(f"workspace/agent_tasks/{task.task_id}.md", content)

    def create_markdown_result(self, result: MarkdownResultFile) -> Path:
        content = "\n".join(
            [
                f"# Result {result.task_id}",
                "",
                f"- producing_agent: {result.producing_agent}",
                f"- status: {result.status}",
                "",
                "## Summary",
                result.summary,
                "",
            ]
        )
        return self.write_text(f"workspace/agent_tasks/{result.task_id}.result.md", content)

    def read_markdown(self, relative_path: str) -> str:
        return self.read_text(relative_path)
