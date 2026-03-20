from __future__ import annotations

import uuid

from shared.schemas import MarkdownResultFile, MarkdownTaskFile
from storage.files.repository import FileRepository


class MarkdownWorkspace:
    def __init__(self, file_repo: FileRepository) -> None:
        self.file_repo = file_repo

    def create_task(self, source_agent: str, target_agent: str, intent: str, input_context: str) -> str:
        task = MarkdownTaskFile(
            task_id=str(uuid.uuid4()),
            source_agent=source_agent,
            target_agent=target_agent,
            intent=intent,
            input_context=input_context,
        )
        self.file_repo.create_markdown_task(task)
        return task.task_id

    def complete_task(self, task_id: str, producing_agent: str, summary: str) -> str:
        result = MarkdownResultFile(task_id=task_id, producing_agent=producing_agent, summary=summary)
        self.file_repo.create_markdown_result(result)
        return task_id
