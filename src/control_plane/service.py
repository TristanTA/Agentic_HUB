from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException

from control_plane.builder_service import BuilderService
from control_plane.commands import parse_management_command
from control_plane.config_editor import ConfigEditor
from control_plane.log_reader import LogReader
from control_plane.manager_agent import ManagerAgent
from control_plane.process_control import ProcessController
from hub.registry.loader import load_registries
from shared.schemas import AgentScorecard, ManagementAction, VantaChangeRecord, VantaScorecard
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
        self.runtime = None

    def bind_runtime(self, runtime) -> None:
        self.runtime = runtime
        setattr(self.runtime, "control_plane", self)

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

    def hub_overview(self) -> dict:
        if self.runtime is not None:
            return {"status": "ok", **self.runtime.hub_status()}
        return {"status": "ok", "hub": self.status(), "health": self.health()}

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

    def tail_logs(self, target: str = "hub", lines: int = 20) -> dict:
        if target == "telegram":
            path = self.root_dir / "logs" / "telegram_runner.log"
            content = path.read_text(encoding="utf-8").splitlines()[-lines:] if path.exists() else []
            return {"status": "ok", "target": target, "lines": content}
        return {"status": "ok", "target": target, "lines": self.logs.tail_human_log(lines=lines)}

    def inspect_run_trace(self, run_id: str) -> dict:
        trace = self.logs.inspect_run_trace(run_id)
        if trace is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return trace

    def edit_prompt(self, relative_path: str, content: str) -> dict:
        previous_content = self.file_repo.read_text(relative_path) if (self.root_dir / relative_path).exists() else ""
        path = self.editor.edit_markdown(relative_path, content)
        change = self._record_vanta_change("prompt", relative_path, previous_content, content, "Prompt update")
        self._audit("edit_prompt", relative_path, {}, "updated")
        return {"path": str(path), "change_id": change.change_id}

    def edit_agent_config(self, agent_id: str, updates: dict) -> dict:
        previous_content = (self.root_dir / "configs" / "agents.yaml").read_text(encoding="utf-8")
        updated = self.editor.update_section_item("configs/agents.yaml", "agents", agent_id, updates)
        new_content = (self.root_dir / "configs" / "agents.yaml").read_text(encoding="utf-8")
        self._record_vanta_change("agent_config", "configs/agents.yaml", previous_content, new_content, f"Agent config update for {agent_id}")
        self._audit("edit_agent_config", agent_id, updates, "updated")
        return updated

    def edit_skill(self, relative_path: str, content: str) -> dict:
        previous_content = self.file_repo.read_text(relative_path) if (self.root_dir / relative_path).exists() else ""
        path = self.editor.edit_markdown(relative_path, content)
        change = self._record_vanta_change("skill", relative_path, previous_content, content, "Skill update")
        self._audit("edit_skill", relative_path, {}, "updated")
        return {"path": str(path), "change_id": change.change_id}

    def compare_prompt_versions(self, relative_path: str) -> dict:
        path = self.root_dir / relative_path
        content = path.read_text(encoding="utf-8")
        return {"path": str(path), "current_length": len(content)}

    def manager_summary(self) -> dict:
        return self.manager_agent.summarize_operational_risk()

    def _record_vanta_change(self, target_type: str, target_path: str, previous_content: str, new_content: str, reason: str) -> VantaChangeRecord:
        change = VantaChangeRecord(
            change_id=str(uuid.uuid4()),
            target_type=target_type,
            target_path=target_path,
            reason=reason,
            previous_content=previous_content,
            new_content=new_content,
        )
        self.store.record_vanta_change(change)
        return change

    def vanta_changes(self, limit: int = 10) -> dict:
        return {"status": "ok", "changes": [change.model_dump(mode="json") for change in self.store.list_vanta_changes(limit=limit)]}

    def vanta_memory(self, thread_id: str | None = None) -> dict:
        agent_id = "vanta_manager"
        memories = self.store.list_memory_items(agent_id=agent_id, thread_id=thread_id, limit=20)
        state = self.store.get_thread_working_state(thread_id=thread_id, agent_id=agent_id) if thread_id else None
        return {
            "status": "ok",
            "memory_items": [item.model_dump(mode="json") for item in memories],
            "working_state": state.model_dump(mode="json") if state else None,
        }

    def rollback_change(self, change_id: str) -> dict:
        change = self.store.get_vanta_change(change_id)
        if change is None:
            return {"status": "error", "message": f"Unknown change id {change_id}"}
        self.editor.edit_markdown(change.target_path, change.previous_content)
        self.store.mark_vanta_change_rolled_back(change_id, datetime.now(timezone.utc).isoformat())
        self.reload_config()
        self._audit("rollback_change", change.target_path, {"change_id": change_id}, "rolled_back")
        return {"status": "ok", "change_id": change_id, "target_path": change.target_path}

    def agent_scorecards(self) -> dict:
        tasks = self.store.list_agent_tasks(limit=200)
        by_agent: dict[str, list] = {}
        for task in tasks:
            by_agent.setdefault(task.assigned_to, []).append(task)
        routed_agents = {rule.target_id for rule in self.bundle.routes if rule.target_type.value == "agent"}
        cards = []
        for agent_id, spec in sorted(self.bundle.agents.items()):
            agent_tasks = by_agent.get(agent_id, [])
            completed = sum(1 for task in agent_tasks if str(task.status) == "completed")
            failed = sum(1 for task in agent_tasks if str(task.status) == "failed")
            total = len(agent_tasks)
            cards.append(
                AgentScorecard(
                    agent_id=agent_id,
                    goal_clarity=4 if spec.purpose.strip() else 1,
                    tool_fit=4 if spec.allowed_tools else 1,
                    model_fit=2 if spec.preferred_model == "echo_model" else 4,
                    routing_fit=4 if agent_id in routed_agents or agent_id == self.bundle.hub_config.hub.default_agent else 2,
                    completion_quality=3 if total == 0 else max(1, min(5, 3 + completed - failed)),
                    failure_rate=5 if total == 0 else max(1, 5 - failed),
                    summary=f"{completed}/{total} completed; model={spec.preferred_model}; tools={len(spec.allowed_tools)}",
                ).model_dump(mode="json")
            )
        return {"status": "ok", "scorecards": cards}

    def vanta_focus(self) -> dict:
        scorecards = self.agent_scorecards()["scorecards"]
        weakest = min(
            scorecards,
            key=lambda item: item["goal_clarity"] + item["tool_fit"] + item["model_fit"] + item["routing_fit"] + item["completion_quality"] + item["failure_rate"],
        )
        latest_errors = self.inspect_recent_errors()
        focus = "hub_health" if latest_errors else "agent_effectiveness"
        target = "runtime_errors" if latest_errors else weakest["agent_id"]
        reason = "Recent errors need attention first." if latest_errors else f"Weakest scorecard currently belongs to {weakest['agent_id']}."
        return {"status": "ok", "focus_area": focus, "target": target, "reason": reason, "scorecard": weakest}

    def vanta_scorecard(self) -> dict:
        lessons = self.store.list_vanta_lessons(limit=20)
        reviews = self.store.list_vanta_reviews(limit=20)
        repeated_mistake_risk = 5 if len(lessons) <= 1 else max(1, 5 - min(4, len(lessons) // 3))
        scorecard = VantaScorecard(
            diagnosis_quality=4 if reviews else 2,
            intervention_success_rate=4 if self.store.list_vanta_changes(limit=5) else 2,
            question_quality=4,
            critique_quality=4,
            repeated_mistake_risk=repeated_mistake_risk,
            self_update_quality=4 if lessons else 2,
            summary=f"{len(reviews)} reviews, {len(lessons)} lessons, {len(self.store.list_vanta_changes(limit=20))} tracked changes.",
        )
        return {"status": "ok", "scorecard": scorecard.model_dump(mode="json")}

    def list_routes(self) -> dict:
        return {"status": "ok", "routes": [rule.model_dump(mode="json") for rule in self.bundle.routes]}

    def inspect_agent(self, agent_id: str) -> dict:
        if self.runtime is not None:
            return {"status": "ok", "agent": self.runtime.inspect_agent(agent_id)}
        return {"status": "ok", "agent": self.bundle.agents[agent_id].model_dump(mode="json")}

    def vanta_docs(self) -> dict:
        if self.runtime is not None:
            return {"status": "ok", "self": self.runtime.vanta_self_context()}
        spec = self.bundle.agents["vanta_manager"]
        return {
            "status": "ok",
            "self": {
                "agent_id": spec.id,
                "soul_file": spec.soul_file,
                "prompt_file": spec.prompt_file,
                "config_file": "agents/vanta_manager/config.yaml",
                "loadout_file": "agents/vanta_manager/loadout.yaml",
                "registry_file": "configs/agents.yaml",
            },
        }

    def vanta_lessons(self, limit: int = 10) -> dict:
        return {"status": "ok", "lessons": [lesson.model_dump(mode="json") for lesson in self.store.list_vanta_lessons(limit=limit)]}

    def vanta_status(self) -> dict:
        latest_review = self.store.latest_vanta_review()
        latest_lesson = self.store.list_vanta_lessons(limit=1)
        recent_changes = self.store.list_vanta_changes(limit=3)
        return {
            "status": "ok",
            "current_focus": latest_review.focus_area if latest_review else "agent_effectiveness",
            "last_review": latest_review.model_dump(mode="json") if latest_review else None,
            "last_lesson": latest_lesson[0].model_dump(mode="json") if latest_lesson else None,
            "recent_changes": [change.model_dump(mode="json") for change in recent_changes],
            "autonomy": self.bundle.hub_config.vanta.model_dump(),
        }

    def vanta_review(self) -> dict:
        latest_review = self.store.latest_vanta_review()
        if latest_review is None:
            return {"status": "ok", "message": "No Vanta reviews have been recorded yet."}
        return {"status": "ok", "review": latest_review.model_dump(mode="json")}

    def review_agent(self, agent_id: str) -> dict:
        agent = self.bundle.agents[agent_id]
        findings = [
            f"Model: {agent.preferred_model}",
            f"Tools: {', '.join(agent.allowed_tools) or 'none'}",
            f"Skills: {', '.join(agent.skill_ids) or 'none'}",
            f"Exposure: {agent.exposure_mode.value}",
        ]
        concerns = []
        if not agent.allowed_tools:
            concerns.append("Agent has no tools.")
        if agent.preferred_model == "echo_model":
            concerns.append("Agent is on the placeholder echo model.")
        return {"status": "ok", "agent_id": agent_id, "findings": findings, "concerns": concerns}

    def improve_agent(self, agent_id: str) -> dict:
        review = self.review_agent(agent_id)
        concerns = review.get("concerns", [])
        actions: list[str] = []
        if "Agent is on the placeholder echo model." in concerns and agent_id != "vanta_manager":
            updated = self.edit_agent_config(agent_id, {"preferred_model": "openai_gpt5_mini"})
            actions.append(f"Updated {agent_id} to openai_gpt5_mini.")
            return {"status": "updated", "agent": updated, "actions": actions, "review": review}
        return {"status": "ok", "actions": actions, "review": review}

    def list_agents(self) -> dict:
        return {
            "status": "ok",
            "agents": [
                {
                    "id": spec.id,
                    "purpose": spec.purpose,
                    "exposure_mode": spec.exposure_mode.value,
                    "execution_mode": spec.execution_mode.value,
                    "adapter_type": getattr(spec.adapter_type, "value", spec.adapter_type),
                    "enabled": spec.enabled,
                }
                for spec in sorted(self.bundle.agents.values(), key=lambda item: item.id)
            ],
        }

    def list_workers(self) -> dict:
        if self.runtime is not None:
            return {"status": "ok", "workers": self.runtime.adapters.health_report()}
        return {
            "status": "ok",
            "workers": [
                {
                    "id": spec.id,
                    "exposure_mode": spec.exposure_mode.value,
                    "execution_mode": spec.execution_mode.value,
                    "can_receive_tasks": spec.can_receive_tasks,
                    "can_receive_messages": spec.can_receive_messages,
                }
                for spec in sorted(self.bundle.agents.values(), key=lambda item: item.id)
                if spec.can_receive_tasks or spec.can_receive_messages
            ],
        }

    def delegate_task(self, *, assigned_to: str, goal: str, input_context: str = "", created_by: str = "vanta_manager") -> dict:
        if self.runtime is None:
            return {"status": "error", "message": "Runtime is not bound; cannot delegate tasks from the control plane."}
        task = self.runtime.task_service.create_and_dispatch_task(
            created_by=created_by,
            assigned_to=assigned_to,
            goal=goal,
            input_context=input_context or goal,
        )
        self._audit("delegate_task", assigned_to, {"goal": goal, "created_by": created_by}, task.status.value)
        return {"status": "ok", "task": task.model_dump(mode="json")}

    def list_tasks(self, *, assigned_to: str | None = None, created_by: str | None = None, limit: int = 20) -> dict:
        tasks = self.store.list_agent_tasks(assigned_to=assigned_to, created_by=created_by, limit=limit)
        return {"status": "ok", "tasks": [task.model_dump(mode="json") for task in tasks]}

    def promote_agent(self, agent_id: str, exposure_mode: str, telegram: dict | None = None) -> dict:
        updates = {"exposure_mode": exposure_mode}
        if telegram is not None:
            updates["telegram"] = telegram
            updates["telegram_profile_id"] = agent_id if exposure_mode == "standalone_telegram" else None
        updated = self.editor.update_section_item("configs/agents.yaml", "agents", agent_id, updates)
        local_config_path = f"agents/{agent_id}/config.yaml"
        if (self.root_dir / local_config_path).exists():
            self.editor.update_yaml_file(local_config_path, updates)
        self._audit("promote_agent", agent_id, updates, "updated")
        self.bundle = load_registries(self.root_dir)
        return {"status": "updated", "agent": updated}

    def attach_external_agent(
        self,
        *,
        name: str,
        purpose: str,
        adapter_type: str,
        command: str = "",
        bot_token_env: str = "",
        chat_id: str = "",
        exposure_mode: str = "hub_addressable",
    ) -> dict:
        adapter_config: dict = {}
        telegram: dict = {}
        if adapter_type == "python_process":
            adapter_config["command"] = command
        else:
            adapter_config["bot_token_env"] = bot_token_env
            if chat_id:
                adapter_config["chat_id"] = chat_id
            if exposure_mode == "standalone_telegram":
                telegram = {"bot_token_env": bot_token_env, "default_chat_id": chat_id, "owns_polling": False}
        result = self.builder.attach_external_agent(
            name=name,
            purpose=purpose,
            adapter_type=adapter_type,
            adapter_config=adapter_config,
            exposure_mode=exposure_mode,
            telegram=telegram,
        )
        self._audit("attach_external_agent", result["agent_id"], result, "created")
        self.bundle = load_registries(self.root_dir)
        return result

    def handle_management_command(self, text: str) -> dict:
        command = parse_management_command(text)
        if command is None:
            return {"status": "ignored", "reason": "not_a_command"}
        if command.name == "help":
            return {
                "status": "ok",
                "message": "\n".join(
                    [
                        "/status /health /errors /trace /logs /routes",
                        "/agents /agent /workers /tasks /delegate",
                        "/review_agent /improve_agent",
                        "/vanta_status /vanta_focus /vanta_docs /vanta_lessons /vanta_changes /vanta_review /vanta_scorecard",
                        "/scorecards /rollback_change <change_id>",
                        "/reload /pause /resume /restart /new_agent",
                    ]
                ),
            }

        if command.name == "status":
            return self.hub_overview()
        if command.name == "health":
            return {"status": "ok", "health": self.health()}
        if command.name == "reload":
            return self.reload_config()
        if command.name == "pause":
            return self.pause_hub()
        if command.name == "resume":
            return self.resume_hub()
        if command.name == "restart":
            return self.restart_hub()
        if command.name == "errors":
            return {"status": "ok", "errors": self.inspect_recent_errors()[: int(command.options.get("limit", "10"))]}
        if command.name == "trace":
            if not command.args:
                return {"status": "needs_input", "command": command.name, "message": "Usage: /trace <run_id>"}
            return {"status": "ok", "trace": self.inspect_run_trace(command.args[0])}
        if command.name == "logs":
            return self.tail_logs(target=command.options.get("target", "hub"), lines=int(command.options.get("lines", "20")))
        if command.name == "routes":
            return self.list_routes()
        if command.name == "agent":
            if not command.args:
                return {"status": "needs_input", "command": command.name, "message": "Usage: /agent <agent_id>"}
            return self.inspect_agent(command.args[0])
        if command.name == "vanta_docs":
            return self.vanta_docs()
        if command.name == "vanta_lessons":
            return self.vanta_lessons(limit=int(command.options.get("limit", "10")))
        if command.name == "vanta_changes":
            return self.vanta_changes(limit=int(command.options.get("limit", "10")))
        if command.name == "vanta_memory":
            return self.vanta_memory(thread_id=command.options.get("thread_id"))
        if command.name == "vanta_status":
            return self.vanta_status()
        if command.name == "vanta_focus":
            return self.vanta_focus()
        if command.name == "vanta_scorecard":
            return self.vanta_scorecard()
        if command.name == "vanta_review":
            return self.vanta_review()
        if command.name == "scorecards":
            return self.agent_scorecards()
        if command.name == "rollback_change":
            if not command.args:
                return {"status": "needs_input", "command": command.name, "message": "Usage: /rollback_change <change_id>"}
            return self.rollback_change(command.args[0])
        if command.name == "review_agent":
            if not command.args:
                return {"status": "needs_input", "command": command.name, "message": "Usage: /review_agent <agent_id>"}
            return self.review_agent(command.args[0])
        if command.name == "improve_agent":
            if not command.args:
                return {"status": "needs_input", "command": command.name, "message": "Usage: /improve_agent <agent_id>"}
            return self.improve_agent(command.args[0])
        if command.name == "agents":
            return self.list_agents()
        if command.name == "workers":
            return self.list_workers()
        if command.name == "tasks":
            return self.list_tasks(
                assigned_to=command.options.get("assigned_to"),
                created_by=command.options.get("created_by"),
                limit=int(command.options.get("limit", "20")),
            )
        if command.name == "delegate":
            if "assigned_to" not in command.options or "goal" not in command.options:
                return {
                    "status": "needs_input",
                    "command": command.name,
                    "message": "Usage: /delegate --assigned_to <agent_id> --goal \"What should be done\" [--input_context \"...\"]",
                }
            return self.delegate_task(
                assigned_to=command.options["assigned_to"],
                goal=command.options["goal"],
                input_context=command.options.get("input_context", ""),
            )
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
                soul_prompt=command.options.get("soul_prompt", ""),
                exposure_mode=command.options.get("exposure_mode", "internal_worker"),
                execution_mode=command.options.get("execution_mode", "native_hub"),
                adapter_type=command.options.get("adapter_type", "native"),
                can_receive_tasks=command.options.get("can_receive_tasks", "true").lower() != "false",
                can_receive_messages=command.options.get("can_receive_messages", "false").lower() == "true",
            )
            self._audit(
                "create_agent",
                result["agent_id"],
                {"command": text},
                result["status"],
            )
            return result
        if command.name == "attach_agent":
            if not command.args or "purpose" not in command.options or "adapter_type" not in command.options:
                return {
                    "status": "needs_input",
                    "command": command.name,
                    "message": "Usage: /attach_agent <agent_id> --purpose \"What it does\" --adapter_type <python_process|telegram_bot|openclaw|custom> [--command ...] [--bot_token_env ...] [--chat_id ...] [--exposure_mode hub_addressable|standalone_telegram]",
                }
            return self.attach_external_agent(
                name=command.args[0],
                purpose=command.options["purpose"],
                adapter_type=command.options["adapter_type"],
                command=command.options.get("command", ""),
                bot_token_env=command.options.get("bot_token_env", ""),
                chat_id=command.options.get("chat_id", ""),
                exposure_mode=command.options.get("exposure_mode", "hub_addressable"),
            )
        if command.name == "promote_agent":
            if not command.args or "exposure_mode" not in command.options:
                return {
                    "status": "needs_input",
                    "command": command.name,
                    "message": "Usage: /promote_agent <agent_id> --exposure_mode <internal_worker|hub_addressable|standalone_telegram> [--bot_token_env ENV]",
                }
            telegram = None
            if command.options["exposure_mode"] == "standalone_telegram":
                telegram = {
                    "bot_token_env": command.options.get("bot_token_env", ""),
                    "allowed_chat_ids": [],
                    "owns_polling": True,
                }
            return self.promote_agent(command.args[0], command.options["exposure_mode"], telegram=telegram)

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
                f"Exposure: {result.get('registered_agent', {}).get('exposure_mode', '')}",
                f"Execution: {result.get('registered_agent', {}).get('execution_mode', '')}",
                f"Soul: {files.get('soul', '')}",
                f"Prompt: {files.get('prompt', '')}",
                f"Config: {files.get('config', '')}",
            ]
            return "\n".join(lines)
        if status == "updated" and result.get("agent"):
            agent = result["agent"]
            return f"Updated agent: {agent.get('id', '')}\nExposure: {agent.get('exposure_mode', '')}"
        if status == "needs_input":
            return result.get("message", "Missing required input.")
        if status == "unsupported":
            return result.get("message", "Unsupported command.")
        if "message" in result and len(result) <= 2:
            return result["message"]
        if "agents" in result:
            return "\n".join(
                f"{item['id']} | {item['exposure_mode']} | {item['execution_mode']}"
                for item in result["agents"]
            ) or "No agents found."
        if "workers" in result:
            lines = []
            for item in result["workers"]:
                if "agent_id" in item:
                    lines.append(f"{item['agent_id']} | {item['status']} | {item.get('adapter_type', '')}")
                else:
                    lines.append(f"{item['id']} | tasks={item['can_receive_tasks']} | messages={item['can_receive_messages']}")
            return "\n".join(lines) or "No workers found."
        if "tasks" in result:
            return "\n".join(
                f"{item['task_id']} | {item['assigned_to']} | {item['status']}"
                for item in result["tasks"]
            ) or "No tasks found."
        if "task" in result:
            task = result["task"]
            return f"{task['task_id']} | {task['assigned_to']} | {task['status']}"
        if "hub" in result and "health" in result:
            return f"Hub: {result['hub']}\nHealth: {result['health']}"
        if "health" in result and result.get("status") == "ok":
            return f"Health: {result['health']}"
        if "errors" in result:
            errors = result["errors"]
            if not errors:
                return "No recent errors."
            return "\n".join(f"{item['run_id']}: {item['errors']}" for item in errors[:5])
        if "trace" in result:
            trace = result["trace"]
            return f"{trace['run_id']} | latency={trace['latency_ms']} | errors={trace['errors']}"
        if "routes" in result:
            return "\n".join(
                f"{item['id']} | {item['target_type']} -> {item['target_id']}"
                for item in result["routes"]
            ) or "No routes found."
        if "agent" in result:
            agent = result["agent"]
            return (
                f"{agent['id']} | model={agent.get('preferred_model', '')} | "
                f"tools={','.join(agent.get('allowed_tools', []))} | skills={','.join(agent.get('skill_ids', []))}"
            )
        if "self" in result:
            payload = result["self"]
            return "\n".join(
                [
                    f"Agent: {payload['agent_id']}",
                    f"Soul: {payload['soul_file']}",
                    f"Prompt: {payload['prompt_file']}",
                    f"Config: {payload['config_file']}",
                    f"Loadout: {payload['loadout_file']}",
                ]
            )
        if "lessons" in result:
            lessons = result["lessons"]
            if not lessons:
                return "No Vanta lessons recorded."
            return "\n".join(f"{item['category']}: {item['updated_rule']}" for item in lessons[:5])
        if "changes" in result:
            changes = result["changes"]
            if not changes:
                return "No Vanta changes recorded."
            return "\n".join(f"{item['change_id']} | {item['target_path']} | {item['reason']}" for item in changes[:5])
        if "memory_items" in result:
            memory_lines = [f"{item['kind']}: {item['value']}" for item in result["memory_items"][:8]]
            state = result.get("working_state")
            state_line = f"Working state: {state}" if state else "Working state: none"
            return "\n".join(memory_lines + [state_line]) if memory_lines else state_line
        if "last_review" in result or "current_focus" in result:
            recent = result.get("recent_changes", [])
            recent_summary = ", ".join(item["change_id"] for item in recent) if recent else "none"
            return (
                f"Focus: {result.get('current_focus', '')}\n"
                f"Autonomy: {result.get('autonomy', {})}\n"
                f"Last review: {result.get('last_review', {})}\n"
                f"Last lesson: {result.get('last_lesson', {})}\n"
                f"Recent changes: {recent_summary}"
            )
        if "focus_area" in result and "target" in result:
            return f"Focus: {result['focus_area']}\nTarget: {result['target']}\nReason: {result['reason']}"
        if "scorecards" in result:
            return "\n".join(
                f"{item['agent_id']} | model={item['model_fit']} | tools={item['tool_fit']} | completion={item['completion_quality']}"
                for item in result["scorecards"][:10]
            )
        if "scorecard" in result:
            scorecard = result["scorecard"]
            if "agent_id" in scorecard:
                return f"{scorecard['agent_id']} | {scorecard['summary']}"
            return scorecard["summary"]
        if result.get("change_id") and result.get("target_path"):
            return f"Rolled back {result['change_id']} -> {result['target_path']}"
        if "review" in result:
            review = result["review"]
            return f"Review {review['review_id']} | focus={review['focus_area']}\nSummary: {review['summary']}"
        if "findings" in result and "concerns" in result:
            return "\n".join(result["findings"] + result["concerns"])
        if "lines" in result:
            return "\n".join(result["lines"]) or "No log lines found."
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

    @app.get("/routes")
    def routes():
        return service.list_routes()

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

    @app.get("/vanta-status")
    def vanta_status():
        return service.vanta_status()

    @app.get("/vanta-lessons")
    def vanta_lessons():
        return service.vanta_lessons()

    @app.post("/agents/{agent_id}")
    def edit_agent(agent_id: str, updates: dict):
        return service.edit_agent_config(agent_id, updates)

    @app.post("/commands")
    def command(payload: dict):
        return service.handle_management_command(payload.get("text", ""))

    return app
