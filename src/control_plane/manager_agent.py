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
                "--model <model_id> [--skills skill_a,skill_b] [--tools tool_a,tool_b]"
            )
        if command.name in {"status", "reload", "pause", "resume", "restart", "errors"}:
            return f"Usage: /{command.name}"
        return f"Unknown management command: /{command.name}"
