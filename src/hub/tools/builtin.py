from __future__ import annotations

import json

from hub.outputs.telegram import TelegramOutputAdapter
from shared.schemas import AgentContext, ToolResult
from storage.files.repository import FileRepository
from storage.sqlite.db import SQLiteStore


class WorkspaceNoteTool:
    id = "workspace_note"

    def __init__(self, file_repo: FileRepository) -> None:
        self.file_repo = file_repo

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        filename = tool_input.get("filename", f"{context.run_id}.md")
        content = tool_input.get("content", "")
        relative_path = f"workspace/{context.run_id}/{filename}"
        path = self.file_repo.write_text(relative_path, content)
        return ToolResult(tool_id=self.id, success=True, output={"path": str(path)})


class TraceLookupTool:
    id = "trace_lookup"

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        run_id = tool_input.get("run_id", "")
        trace = self.store.get_run_trace(run_id)
        if trace is None:
            return ToolResult(tool_id=self.id, success=False, error=f"Run {run_id} not found")
        return ToolResult(tool_id=self.id, success=True, output=trace)


class FileReadTool:
    id = "file_read"

    def __init__(self, file_repo: FileRepository) -> None:
        self.file_repo = file_repo

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        relative_path = self._normalize_path(tool_input.get("path", ""))
        if not relative_path:
            return ToolResult(tool_id=self.id, success=False, error="path is required")
        try:
            content = self.file_repo.read_text(relative_path)
        except FileNotFoundError:
            return ToolResult(tool_id=self.id, success=False, error=f"{relative_path} not found")
        return ToolResult(tool_id=self.id, success=True, output={"path": relative_path, "content": content})

    def _normalize_path(self, path_value: str) -> str:
        path = str(path_value or "").strip().replace("\\", "/")
        if not path or path.startswith("/") or ".." in path.split("/"):
            return ""
        return path


class FileWriteTool:
    id = "file_write"

    def __init__(self, file_repo: FileRepository) -> None:
        self.file_repo = file_repo

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        relative_path = self._normalize_path(tool_input.get("path", ""))
        content = tool_input.get("content", "")
        if not relative_path:
            return ToolResult(tool_id=self.id, success=False, error="path is required")
        path = self.file_repo.write_text(relative_path, str(content))
        return ToolResult(tool_id=self.id, success=True, output={"path": str(path)})

    def _normalize_path(self, path_value: str) -> str:
        path = str(path_value or "").strip().replace("\\", "/")
        if not path or path.startswith("/") or ".." in path.split("/"):
            return ""
        return path


class MessageUserTool:
    id = "message_user"

    def __init__(self, file_repo: FileRepository, telegram_output: TelegramOutputAdapter) -> None:
        self.file_repo = file_repo
        self.telegram_output = telegram_output

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        text = str(tool_input.get("text", "")).strip()
        if not text:
            return ToolResult(tool_id=self.id, success=False, error="text is required")
        bot_token_env = str(context.event.metadata.get("bot_token_env", "")).strip()
        relative_path = f"workspace/{context.run_id}/messages_to_user.json"
        path = self.file_repo.write_text(
            relative_path,
            json.dumps(
                {
                    "thread_id": context.event.thread_id,
                    "text": text,
                },
                indent=2,
            ),
        )
        delivery_adapter = self.telegram_output
        if bot_token_env:
            delivery_adapter = TelegramOutputAdapter(enabled=self.telegram_output.enabled, bot_token_env=bot_token_env)
        delivery = delivery_adapter.send({"thread_id": context.event.thread_id, "text": text})
        return ToolResult(
            tool_id=self.id,
            success=True,
            output={"path": str(path), "thread_id": context.event.thread_id, "delivery": delivery},
        )


class DelegateTaskTool:
    id = "delegate_task"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        assigned_to = str(tool_input.get("assigned_to", "")).strip()
        goal = str(tool_input.get("goal", "")).strip()
        input_context = str(tool_input.get("input_context", "")).strip() or goal
        if not assigned_to or not goal:
            return ToolResult(tool_id=self.id, success=False, error="assigned_to and goal are required")
        task = self.runtime.task_service.create_and_dispatch_task(
            created_by=context.agent_id or "manager",
            assigned_to=assigned_to,
            goal=goal,
            input_context=input_context,
        )
        return ToolResult(tool_id=self.id, success=True, output=task.model_dump(mode="json"))


class GetTaskTool:
    id = "get_task"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        task_id = str(tool_input.get("task_id", "")).strip()
        if not task_id:
            return ToolResult(tool_id=self.id, success=False, error="task_id is required")
        task = self.runtime.task_service.get_task(task_id)
        if task is None:
            return ToolResult(tool_id=self.id, success=False, error=f"{task_id} not found")
        return ToolResult(tool_id=self.id, success=True, output=task.model_dump(mode="json"))


class ListTasksTool:
    id = "list_tasks"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        assigned_to = str(tool_input.get("assigned_to", "")).strip() or None
        created_by = str(tool_input.get("created_by", "")).strip() or None
        tasks = self.runtime.task_service.list_tasks(assigned_to=assigned_to, created_by=created_by, limit=int(tool_input.get("limit", 20)))
        return ToolResult(tool_id=self.id, success=True, output={"tasks": [task.model_dump(mode="json") for task in tasks]})


class ListAgentsTool:
    id = "list_agents"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        return ToolResult(tool_id=self.id, success=True, output={"agents": self.runtime.list_agent_profiles()})


class WorkerHealthTool:
    id = "worker_health"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        return ToolResult(tool_id=self.id, success=True, output={"workers": self.runtime.adapters.health_report()})


def build_builtin_tools(
    file_repo: FileRepository,
    store: SQLiteStore,
    telegram_output: TelegramOutputAdapter,
    runtime,
) -> dict[str, object]:
    return {
        "workspace_note": WorkspaceNoteTool(file_repo),
        "trace_lookup": TraceLookupTool(store),
        "file_read": FileReadTool(file_repo),
        "file_write": FileWriteTool(file_repo),
        "message_user": MessageUserTool(file_repo, telegram_output),
        "delegate_task": DelegateTaskTool(runtime),
        "get_task": GetTaskTool(runtime),
        "list_tasks": ListTasksTool(runtime),
        "list_agents": ListAgentsTool(runtime),
        "worker_health": WorkerHealthTool(runtime),
    }
