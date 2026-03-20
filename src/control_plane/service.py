from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException

from control_plane.builder_service import BuilderService
from control_plane.commands import parse_management_command
from control_plane.config_editor import ConfigEditor
from control_plane.log_reader import LogReader
from control_plane.manager_agent import ManagerAgent
from control_plane.process_control import ProcessController
from hub.registry.loader import load_registries
from shared.schemas import ManagementAction
from storage.files.repository import FileRepository
from storage.sqlite.db import SQLiteStore


class ControlPlaneService:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.bundle = load_registries(root_dir)
        hub_cfg = self.bundle.hub_config.hub
        self.store = SQLiteStore(root_dir / hub_cfg.sqlite_path)
        self.process = ProcessController(root_dir, root_dir / hub_cfg.pid_path, root_dir / hub_cfg.state_path)
        self.editor = ConfigEditor(root_dir)
        self.file_repo = FileRepository(root_dir)
        self.logs = LogReader(self.store, root_dir / hub_cfg.human_log_path)
        self.manager_agent = ManagerAgent(self.store, root_dir / "prompts", root_dir / "skills")
        self.builder = BuilderService(root_dir, self.editor, self.file_repo)
        self.audit_actor = self.bundle.management_config.audit_actor

    def _audit(self, action: str, target: str, params: dict, result: str) -> None:
        self.store.write_management_action(
            ManagementAction(
                actor=self.audit_actor,
                action=action,
                target=target,
                params=params,
                result=result,
                audit_id=str(uuid.uuid4()),
            )
        )

    def status(self) -> dict:
        return self.process.status()

    def health(self) -> dict:
        return self.store.latest_health() or {"status": "unknown", "details": {}}

    def pause_hub(self) -> dict:
        result = self.process.pause()
        self._audit("pause_hub", "hub", {}, "paused")
        return result

    def resume_hub(self) -> dict:
        result = self.process.resume()
        self._audit("resume_hub", "hub", {}, "running")
        return result

    def restart_hub(self) -> dict:
        result = self.process.restart()
        self._audit("restart_hub", "hub", {}, "restarted")
        return result

    def reload_config(self) -> dict:
        self.bundle = load_registries(self.root_dir)
        self._audit("reload_config", "configs", {}, "reloaded")
        return {"status": "reloaded"}

    def enable_agent(self, agent_id: str) -> dict:
        updated = self.editor.set_enabled_flag("configs/agents.yaml", "agents", agent_id, True)
        self._audit("enable_agent", agent_id, {}, "enabled")
        return updated

    def disable_agent(self, agent_id: str) -> dict:
        updated = self.editor.set_enabled_flag("configs/agents.yaml", "agents", agent_id, False)
        self._audit("disable_agent", agent_id, {}, "disabled")
        return updated

    def enable_tool(self, tool_id: str) -> dict:
        updated = self.editor.set_enabled_flag("configs/tools.yaml", "tools", tool_id, True)
        self._audit("enable_tool", tool_id, {}, "enabled")
        return updated

    def disable_tool(self, tool_id: str) -> dict:
        updated = self.editor.set_enabled_flag("configs/tools.yaml", "tools", tool_id, False)
        self._audit("disable_tool", tool_id, {}, "disabled")
        return updated

    def inspect_recent_errors(self) -> list[dict]:
        return self.logs.inspect_recent_errors()

    def inspect_run_trace(self, run_id: str) -> dict:
        trace = self.logs.inspect_run_trace(run_id)
        if trace is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return trace

    def edit_prompt(self, relative_path: str, content: str) -> dict:
        path = self.editor.edit_markdown(relative_path, content)
        self._audit("edit_prompt", relative_path, {}, "updated")
        return {"path": str(path)}

    def edit_agent_config(self, agent_id: str, updates: dict) -> dict:
        updated = self.editor.update_section_item("configs/agents.yaml", "agents", agent_id, updates)
        self._audit("edit_agent_config", agent_id, updates, "updated")
        return updated

    def edit_skill(self, relative_path: str, content: str) -> dict:
        path = self.editor.edit_markdown(relative_path, content)
        self._audit("edit_skill", relative_path, {}, "updated")
        return {"path": str(path)}

    def compare_prompt_versions(self, relative_path: str) -> dict:
        path = self.root_dir / relative_path
        content = path.read_text(encoding="utf-8")
        return {"path": str(path), "current_length": len(content)}

    def manager_summary(self) -> dict:
        return self.manager_agent.summarize_operational_risk()

    def handle_management_command(self, text: str) -> dict:
        command = parse_management_command(text)
        if command is None:
            return {"status": "ignored", "reason": "not_a_command"}

        if command.name == "status":
            return {"status": "ok", "hub": self.status(), "health": self.health()}
        if command.name == "reload":
            return self.reload_config()
        if command.name == "pause":
            return self.pause_hub()
        if command.name == "resume":
            return self.resume_hub()
        if command.name == "restart":
            return self.restart_hub()
        if command.name == "errors":
            return {"status": "ok", "errors": self.inspect_recent_errors()}
        if command.name == "new_agent":
            if not command.args or "purpose" not in command.options or "model" not in command.options:
                return {
                    "status": "needs_input",
                    "command": command.name,
                    "message": self.manager_agent.describe_command_help(command),
                }

            result = self.builder.create_agent(
                name=command.args[0],
                purpose=command.options["purpose"],
                model=command.options["model"],
                skills=command.options.get("skills", ""),
                tools=command.options.get("tools", ""),
            )
            self._audit(
                "create_agent",
                result["agent_id"],
                {"command": text},
                result["status"],
            )
            return result

        return {
            "status": "unsupported",
            "command": command.name,
            "message": self.manager_agent.describe_command_help(command),
        }

    def format_management_result(self, result: dict) -> str:
        status = result.get("status", "ok")
        if status == "created" and result.get("agent_id"):
            files = result.get("files", {})
            lines = [
                f"Created agent: {result['agent_id']}",
                f"Soul: {files.get('soul', '')}",
                f"Prompt: {files.get('prompt', '')}",
                f"Config: {files.get('config', '')}",
            ]
            return "\n".join(lines)
        if status == "needs_input":
            return result.get("message", "Missing required input.")
        if status == "unsupported":
            return result.get("message", "Unsupported command.")
        if "hub" in result and "health" in result:
            return f"Hub: {result['hub']}\nHealth: {result['health']}"
        if "errors" in result:
            errors = result["errors"]
            if not errors:
                return "No recent errors."
            return "\n".join(f"{item['run_id']}: {item['errors']}" for item in errors[:5])
        return str(result)


def build_app(root_dir: Path) -> FastAPI:
    service = ControlPlaneService(root_dir)
    app = FastAPI(title="Personal AI Hub Control Plane")

    @app.get("/status")
    def status():
        return service.status()

    @app.get("/health")
    def health():
        return service.health()

    @app.post("/pause")
    def pause():
        return service.pause_hub()

    @app.post("/resume")
    def resume():
        return service.resume_hub()

    @app.post("/restart")
    def restart():
        return service.restart_hub()

    @app.post("/reload-config")
    def reload_config():
        return service.reload_config()

    @app.get("/errors")
    def errors():
        return service.inspect_recent_errors()

    @app.get("/runs/{run_id}")
    def run_trace(run_id: str):
        return service.inspect_run_trace(run_id)

    @app.get("/manager-summary")
    def manager_summary():
        return service.manager_summary()

    @app.post("/agents/{agent_id}")
    def edit_agent(agent_id: str, updates: dict):
        return service.edit_agent_config(agent_id, updates)

    @app.post("/commands")
    def command(payload: dict):
        return service.handle_management_command(payload.get("text", ""))

    return app
