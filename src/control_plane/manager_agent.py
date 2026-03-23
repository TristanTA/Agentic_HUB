from __future__ import annotations

from pathlib import Path

from control_plane.commands import ManagementCommand
from storage.sqlite.db import SQLiteStore


class ManagerAgent:
    def __init__(self, store: SQLiteStore, prompts_dir: Path, skills_dir: Path) -> None:
        self.store = store
        self.prompts_dir = prompts_dir
        self.skills_dir = skills_dir

    def summarize_operational_risk(self) -> dict:
        recent_errors = self.store.recent_errors(limit=5)
        if recent_errors:
            return {
                "status": "attention_needed",
                "recommendation": "Inspect recent failures before changing prompts or restarting the hub.",
                "recent_errors": recent_errors,
            }
        return {
            "status": "stable",
            "recommendation": "No recent runtime errors detected. Safe to review configs or migrate another agent.",
            "recent_errors": [],
        }

    def describe_command_help(self, command: ManagementCommand) -> str:
        if command.name == "new_agent":
            return (
                "Usage: /new_agent <agent_id> --purpose \"What it does\" "
                "--model <model_id> [--skills skill_a,skill_b] [--tools tool_a,tool_b] "
                "[--exposure_mode internal_worker|hub_addressable|standalone_telegram]"
            )
        if command.name == "attach_agent":
            return (
                "Usage: /attach_agent <agent_id> --purpose \"What it does\" "
                "--adapter_type <python_process|telegram_bot|openclaw|custom>"
            )
        if command.name == "promote_agent":
            return (
                "Usage: /promote_agent <agent_id> "
                "--exposure_mode <internal_worker|hub_addressable|standalone_telegram>"
            )
        if command.name == "delegate":
            return "Usage: /delegate --assigned_to <agent_id> --goal \"What should be done\" [--input_context \"...\"]"
        if command.name == "trace":
            return "Usage: /trace <run_id>"
        if command.name == "logs":
            return "Usage: /logs [--target hub|telegram] [--lines 20]"
        if command.name in {"agent", "review_agent", "improve_agent"}:
            return f"Usage: /{command.name} <agent_id>"
        if command.name == "rollback_change":
            return "Usage: /rollback_change <change_id>"
        if command.name == "vanta_memory":
            return "Usage: /vanta_memory [--thread_id <chat_id>]"
        if command.name in {"status", "health", "reload", "pause", "resume", "restart", "errors", "routes", "scorecards", "vanta_docs", "vanta_lessons", "vanta_changes", "vanta_status", "vanta_focus", "vanta_review", "vanta_scorecard", "agents", "workers", "tasks"}:
            return f"Usage: /{command.name}"
        return f"Unknown management command: /{command.name}"
