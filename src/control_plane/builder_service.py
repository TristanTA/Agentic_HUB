from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from control_plane.config_editor import ConfigEditor
from storage.files.repository import FileRepository


def _slugify(value: str) -> str:
    lowered = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    lowered = re.sub(r"[^a-z0-9_]", "", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    return lowered


def _csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(slots=True)
class AgentBlueprint:
    agent_id: str
    purpose: str
    preferred_model: str
    allowed_tools: list[str]
    skill_ids: list[str]
    soul_prompt: str = ""
    memory_scope: str = "session"
    timeout: int = 30
    enabled: bool = True
    adapter_type: str = "langchain_markdown"


class BuilderService:
    def __init__(self, root_dir: Path, editor: ConfigEditor, file_repo: FileRepository) -> None:
        self.root_dir = root_dir
        self.editor = editor
        self.file_repo = file_repo

    def create_agent(
        self,
        *,
        name: str,
        purpose: str,
        model: str,
        skills: str = "",
        tools: str = "",
        soul_prompt: str = "",
    ) -> dict:
        agent_id = _slugify(name)
        if not agent_id:
            raise ValueError("Agent name must include letters or numbers")
        if not purpose.strip():
            raise ValueError("Purpose is required")

        bundle = self._load_known_registry_values()
        if agent_id in bundle["agents"]:
            raise ValueError(f"Agent {agent_id} already exists")

        skill_ids = _csv_list(skills) or ["general_style"]
        allowed_tools = _csv_list(tools) or ["workspace_note"]

        unknown_skills = [skill_id for skill_id in skill_ids if skill_id not in bundle["skills"]]
        unknown_tools = [tool_id for tool_id in allowed_tools if tool_id not in bundle["tools"]]
        if model not in bundle["models"]:
            raise ValueError(f"Unknown model {model}")
        if unknown_skills:
            raise ValueError(f"Unknown skills: {', '.join(unknown_skills)}")
        if unknown_tools:
            raise ValueError(f"Unknown tools: {', '.join(unknown_tools)}")

        blueprint = AgentBlueprint(
            agent_id=agent_id,
            purpose=purpose.strip(),
            preferred_model=model,
            allowed_tools=allowed_tools,
            skill_ids=skill_ids,
            soul_prompt=soul_prompt.strip(),
        )
        return self._materialize_agent(blueprint)

    def _materialize_agent(self, blueprint: AgentBlueprint) -> dict:
        agent_dir = self.root_dir / "agents" / blueprint.agent_id
        if agent_dir.exists():
            raise ValueError(f"Agent directory already exists for {blueprint.agent_id}")

        soul_relative_path = f"agents/{blueprint.agent_id}/soul.md"
        local_config_relative_path = f"agents/{blueprint.agent_id}/config.yaml"
        prompt_relative_path = f"prompts/agents/{blueprint.agent_id}.md"

        soul_content = self._build_soul_markdown(blueprint)
        prompt_content = self._build_prompt_markdown(blueprint)
        local_config = {
            "id": blueprint.agent_id,
            "purpose": blueprint.purpose,
            "soul_file": soul_relative_path,
            "prompt_file": prompt_relative_path,
            "preferred_model": blueprint.preferred_model,
            "skill_ids": blueprint.skill_ids,
            "allowed_tools": blueprint.allowed_tools,
            "memory_scope": blueprint.memory_scope,
            "timeout": blueprint.timeout,
            "enabled": blueprint.enabled,
            "adapter_type": blueprint.adapter_type,
        }
        central_config = {
            "id": blueprint.agent_id,
            "purpose": blueprint.purpose,
            "prompt_file": prompt_relative_path,
            "skill_ids": blueprint.skill_ids,
            "allowed_tools": blueprint.allowed_tools,
            "preferred_model": blueprint.preferred_model,
            "memory_scope": blueprint.memory_scope,
            "timeout": blueprint.timeout,
            "enabled": blueprint.enabled,
            "adapter_type": blueprint.adapter_type,
        }

        soul_path = self.file_repo.write_text(soul_relative_path, soul_content)
        prompt_path = self.file_repo.write_text(prompt_relative_path, prompt_content)
        config_path = self.file_repo.write_text(
            local_config_relative_path,
            yaml.safe_dump(local_config, sort_keys=False),
        )
        registered = self.editor.append_section_item("configs/agents.yaml", "agents", central_config)

        return {
            "status": "created",
            "agent_id": blueprint.agent_id,
            "registered_agent": registered,
            "files": {
                "agent_dir": str(agent_dir),
                "soul": str(soul_path),
                "prompt": str(prompt_path),
                "config": str(config_path),
            },
            "next_steps": [
                "Reload the hub config before routing traffic to the new agent.",
                "Review the generated soul and prompt files for agent-specific behavior.",
            ],
        }

    def _load_known_registry_values(self) -> dict[str, set[str]]:
        configs_dir = self.root_dir / "configs"
        agents_payload = yaml.safe_load((configs_dir / "agents.yaml").read_text(encoding="utf-8")) or {}
        skills_payload = yaml.safe_load((configs_dir / "skills.yaml").read_text(encoding="utf-8")) or {}
        tools_payload = yaml.safe_load((configs_dir / "tools.yaml").read_text(encoding="utf-8")) or {}
        models_payload = yaml.safe_load((configs_dir / "models.yaml").read_text(encoding="utf-8")) or {}
        return {
            "agents": {item["id"] for item in agents_payload.get("agents", [])},
            "skills": {item["id"] for item in skills_payload.get("skills", [])},
            "tools": {item["id"] for item in tools_payload.get("tools", [])},
            "models": {item["id"] for item in models_payload.get("models", [])},
        }

    def _build_soul_markdown(self, blueprint: AgentBlueprint) -> str:
        title = blueprint.agent_id.replace("_", " ").title()
        return "\n".join(
            [
                f"# {title} Soul",
                "",
                "## Identity",
                f"You are {title}.",
                "",
                "## Purpose",
                blueprint.purpose,
                "",
                "## Style",
                blueprint.soul_prompt or "Operate clearly and efficiently.",
                "",
                "## Operating Rules",
                "- Stay practical and concise.",
                "- Use the tools you have instead of inventing unavailable capabilities.",
                "- Prefer clear next steps over long explanations.",
                "",
                "## Success Criteria",
                "- The user gets a useful result quickly.",
                "- The output stays aligned with the agent's purpose.",
                "",
            ]
        )

    def _build_prompt_markdown(self, blueprint: AgentBlueprint) -> str:
        title = blueprint.agent_id.replace("_", " ").title()
        tools = ", ".join(blueprint.allowed_tools)
        skills = ", ".join(blueprint.skill_ids)
        return "\n".join(
            [
                f"# {title}",
                "",
                blueprint.purpose,
                "",
                "## Runtime Notes",
                f"- Allowed tools: {tools}",
                f"- Attached skills: {skills}",
                "- Keep responses actionable.",
                "",
            ]
        )
