from __future__ import annotations

import json
import uuid

from hub.outputs.telegram import TelegramOutputAdapter
from shared.schemas import AgentContext, ToolResult, VantaLesson
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


class HubStatusTool:
    id = "hub_status"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        return ToolResult(tool_id=self.id, success=True, output=self.runtime.hub_status())


class RecentErrorsTool:
    id = "recent_errors"

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        limit = int(tool_input.get("limit", 5))
        return ToolResult(tool_id=self.id, success=True, output={"errors": self.store.recent_errors(limit=limit)})


class TraceInspectTool:
    id = "trace_inspect"

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        run_id = str(tool_input.get("run_id", "")).strip()
        if not run_id:
            return ToolResult(tool_id=self.id, success=False, error="run_id is required")
        trace = self.store.get_run_trace(run_id)
        if trace is None:
            return ToolResult(tool_id=self.id, success=False, error=f"{run_id} not found")
        return ToolResult(tool_id=self.id, success=True, output=trace)


class TailLogsTool:
    id = "tail_logs"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        target = str(tool_input.get("target", "hub")).strip() or "hub"
        lines = max(1, int(tool_input.get("lines", 20)))
        if target == "telegram":
            path = self.runtime.root_dir / "logs" / "telegram_runner.log"
        else:
            path = self.runtime.root_dir / self.runtime.bundle.hub_config.hub.human_log_path
        if not path.exists():
            return ToolResult(tool_id=self.id, success=True, output={"target": target, "lines": []})
        return ToolResult(tool_id=self.id, success=True, output={"target": target, "lines": path.read_text(encoding="utf-8").splitlines()[-lines:]})


class ListRoutesTool:
    id = "list_routes"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        return ToolResult(tool_id=self.id, success=True, output={"routes": self.runtime.list_routes()})


class AgentInspectTool:
    id = "agent_inspect"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        agent_id = str(tool_input.get("agent_id", "")).strip()
        if not agent_id:
            return ToolResult(tool_id=self.id, success=False, error="agent_id is required")
        if agent_id not in self.runtime.bundle.agents:
            return ToolResult(tool_id=self.id, success=False, error=f"{agent_id} not found")
        return ToolResult(tool_id=self.id, success=True, output=self.runtime.inspect_agent(agent_id))


class PromptReadTool:
    id = "prompt_read"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        path = str(tool_input.get("path", "")).strip()
        if not path:
            agent_id = str(tool_input.get("agent_id", "")).strip() or (context.agent_id or "")
            if not agent_id or agent_id not in self.runtime.bundle.agents:
                return ToolResult(tool_id=self.id, success=False, error="path or valid agent_id is required")
            path = self.runtime.bundle.agents[agent_id].prompt_file
        return ToolResult(tool_id=self.id, success=True, output=self.runtime.read_prompt_like(path))


class SkillReadTool:
    id = "skill_read"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        skill_id = str(tool_input.get("skill_id", "")).strip()
        if not skill_id or skill_id not in self.runtime.bundle.skills:
            return ToolResult(tool_id=self.id, success=False, error="valid skill_id is required")
        return ToolResult(tool_id=self.id, success=True, output=self.runtime.read_prompt_like(self.runtime.bundle.skills[skill_id].markdown_file))


class AgentUpdateTool:
    id = "agent_update"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        agent_id = str(tool_input.get("agent_id", "")).strip()
        updates = tool_input.get("updates", {})
        if not agent_id or not isinstance(updates, dict):
            return ToolResult(tool_id=self.id, success=False, error="agent_id and updates are required")
        control = getattr(self.runtime, "control_plane", None)
        if control is None:
            return ToolResult(tool_id=self.id, success=False, error="control plane is not bound")
        updated = control.edit_agent_config(agent_id, updates)
        control.reload_config()
        self.runtime.reload_config()
        return ToolResult(tool_id=self.id, success=True, output={"agent": updated})


class PromptUpdateTool:
    id = "prompt_update"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        path = str(tool_input.get("path", "")).strip()
        content = str(tool_input.get("content", ""))
        if not path:
            return ToolResult(tool_id=self.id, success=False, error="path is required")
        control = getattr(self.runtime, "control_plane", None)
        if control is None:
            return ToolResult(tool_id=self.id, success=False, error="control plane is not bound")
        result = control.edit_prompt(path, content)
        control.reload_config()
        self.runtime.reload_config()
        return ToolResult(tool_id=self.id, success=True, output=result)


class SkillUpdateTool:
    id = "skill_update"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        path = str(tool_input.get("path", "")).strip()
        content = str(tool_input.get("content", ""))
        if not path:
            return ToolResult(tool_id=self.id, success=False, error="path is required")
        control = getattr(self.runtime, "control_plane", None)
        if control is None:
            return ToolResult(tool_id=self.id, success=False, error="control plane is not bound")
        result = control.edit_skill(path, content)
        control.reload_config()
        self.runtime.reload_config()
        return ToolResult(tool_id=self.id, success=True, output=result)


class SelfContextTool:
    id = "self_context"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        return ToolResult(tool_id=self.id, success=True, output=self.runtime.vanta_self_context())


class ListLessonsTool:
    id = "list_lessons"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        limit = int(tool_input.get("limit", 10))
        return ToolResult(tool_id=self.id, success=True, output={"lessons": self.runtime.list_vanta_lessons(limit=limit)})


class RecordLessonTool:
    id = "record_lesson"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        required = ["category", "situation", "action_taken", "outcome", "mistake", "updated_rule"]
        missing = [field for field in required if not str(tool_input.get(field, "")).strip()]
        if missing:
            return ToolResult(tool_id=self.id, success=False, error=f"missing fields: {', '.join(missing)}")
        lesson = VantaLesson(
            lesson_id=str(tool_input.get("lesson_id", "")).strip() or str(uuid.uuid4()),
            category=str(tool_input["category"]).strip(),
            situation=str(tool_input["situation"]).strip(),
            action_taken=str(tool_input["action_taken"]).strip(),
            outcome=str(tool_input["outcome"]).strip(),
            mistake=str(tool_input["mistake"]).strip(),
            updated_rule=str(tool_input["updated_rule"]).strip(),
            related_review_id=str(tool_input.get("related_review_id", "")).strip() or None,
        )
        self.runtime.record_vanta_lesson(lesson)
        return ToolResult(tool_id=self.id, success=True, output=lesson.model_dump(mode="json"))


class ListChangesTool:
    id = "list_changes"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        control = getattr(self.runtime, "control_plane", None)
        if control is None:
            return ToolResult(tool_id=self.id, success=False, error="control plane is not bound")
        limit = int(tool_input.get("limit", 10))
        return ToolResult(tool_id=self.id, success=True, output=control.vanta_changes(limit=limit))


class RollbackChangeTool:
    id = "rollback_change"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        control = getattr(self.runtime, "control_plane", None)
        if control is None:
            return ToolResult(tool_id=self.id, success=False, error="control plane is not bound")
        change_id = str(tool_input.get("change_id", "")).strip()
        if not change_id:
            return ToolResult(tool_id=self.id, success=False, error="change_id is required")
        result = control.rollback_change(change_id)
        if result.get("status") == "error":
            return ToolResult(tool_id=self.id, success=False, error=result["message"])
        return ToolResult(tool_id=self.id, success=True, output=result)


class FocusTool:
    id = "focus_status"

    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def invoke(self, context: AgentContext, tool_input: dict) -> ToolResult:
        control = getattr(self.runtime, "control_plane", None)
        if control is None:
            return ToolResult(tool_id=self.id, success=False, error="control plane is not bound")
        return ToolResult(tool_id=self.id, success=True, output=control.vanta_focus())


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
        "hub_status": HubStatusTool(runtime),
        "recent_errors": RecentErrorsTool(store),
        "trace_inspect": TraceInspectTool(store),
        "tail_logs": TailLogsTool(runtime),
        "list_routes": ListRoutesTool(runtime),
        "agent_inspect": AgentInspectTool(runtime),
        "prompt_read": PromptReadTool(runtime),
        "skill_read": SkillReadTool(runtime),
        "agent_update": AgentUpdateTool(runtime),
        "prompt_update": PromptUpdateTool(runtime),
        "skill_update": SkillUpdateTool(runtime),
        "self_context": SelfContextTool(runtime),
        "list_lessons": ListLessonsTool(runtime),
        "record_lesson": RecordLessonTool(runtime),
        "list_changes": ListChangesTool(runtime),
        "rollback_change": RollbackChangeTool(runtime),
        "focus_status": FocusTool(runtime),
    }
