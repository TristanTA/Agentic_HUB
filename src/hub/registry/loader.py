from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from shared.schemas import (
    AgentSpec,
    HubFileConfig,
    ManagementConfig,
    ModelSpec,
    RoutingRule,
    SkillSpec,
    ToolSpec,
    WorkflowSpec,
)


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_agent_profiles(root_dir: Path, central_payload: dict) -> dict[str, AgentSpec]:
    agents: dict[str, AgentSpec] = {
        item["id"]: AgentSpec(**item) for item in central_payload.get("agents", [])
    }
    agents_dir = root_dir / "agents"
    if not agents_dir.exists():
        return agents

    for config_path in agents_dir.glob("*/config.yaml"):
        profile = _read_yaml(config_path)
        if not profile:
            continue
        agent_id = profile.get("id")
        if not agent_id:
            raise ValueError(f"Missing agent id in {config_path}")
        merged = {}
        if agent_id in agents:
            merged.update(agents[agent_id].model_dump())
        merged.update(profile)
        agents[agent_id] = AgentSpec(**merged)
    return agents


@dataclass(slots=True)
class RegistryBundle:
    hub_config: HubFileConfig
    management_config: ManagementConfig
    agents: dict[str, AgentSpec]
    skills: dict[str, SkillSpec]
    tools: dict[str, ToolSpec]
    models: dict[str, ModelSpec]
    workflows: dict[str, WorkflowSpec]
    routes: list[RoutingRule]

    def validate_references(self, root_dir: Path) -> None:
        for agent in self.agents.values():
            if agent.preferred_model not in self.models:
                raise ValueError(f"Agent {agent.id} references unknown model {agent.preferred_model}")
            for tool_id in agent.allowed_tools:
                if tool_id not in self.tools:
                    raise ValueError(f"Agent {agent.id} references unknown tool {tool_id}")
            for skill_id in agent.skill_ids:
                if skill_id not in self.skills:
                    raise ValueError(f"Agent {agent.id} references unknown skill {skill_id}")
            if not (root_dir / agent.prompt_file).exists():
                raise ValueError(f"Missing prompt file for agent {agent.id}: {agent.prompt_file}")
            if agent.soul_file and not (root_dir / agent.soul_file).exists():
                raise ValueError(f"Missing soul file for agent {agent.id}: {agent.soul_file}")
            if agent.execution_mode.value == "external_adapter" and not agent.adapter_config:
                raise ValueError(f"External adapter agent {agent.id} requires adapter_config")
            if agent.exposure_mode.value == "standalone_telegram":
                if not agent.telegram:
                    raise ValueError(f"Standalone Telegram agent {agent.id} requires telegram config")
                if not agent.telegram.get("bot_token_env"):
                    raise ValueError(f"Standalone Telegram agent {agent.id} requires telegram.bot_token_env")
        for skill in self.skills.values():
            if not (root_dir / skill.markdown_file).exists():
                raise ValueError(f"Missing skill file {skill.markdown_file}")
        for rule in self.routes:
            if rule.target_type.value == "agent" and rule.target_id not in self.agents:
                raise ValueError(f"Unknown routed agent {rule.target_id}")
            if rule.target_type.value == "workflow" and rule.target_id not in self.workflows:
                raise ValueError(f"Unknown routed workflow {rule.target_id}")


def load_registries(root_dir: Path) -> RegistryBundle:
    config_dir = root_dir / "configs"
    hub_payload = _read_yaml(config_dir / "hub.yaml")
    agents_payload = _read_yaml(config_dir / "agents.yaml")
    tools_payload = _read_yaml(config_dir / "tools.yaml")
    models_payload = _read_yaml(config_dir / "models.yaml")
    routing_payload = _read_yaml(config_dir / "routing.yaml")
    workflows_payload = _read_yaml(config_dir / "workflows.yaml")
    skills_payload = _read_yaml(config_dir / "skills.yaml")
    management_payload = _read_yaml(config_dir / "management.yaml")

    bundle = RegistryBundle(
        hub_config=HubFileConfig(**hub_payload),
        management_config=ManagementConfig(**management_payload["management"]),
        agents=_load_agent_profiles(root_dir, agents_payload),
        skills={item["id"]: SkillSpec(**item) for item in skills_payload.get("skills", [])},
        tools={item["id"]: ToolSpec(**item) for item in tools_payload.get("tools", [])},
        models={item["id"]: ModelSpec(**item) for item in models_payload.get("models", [])},
        workflows={item["id"]: WorkflowSpec(**item) for item in workflows_payload.get("workflows", [])},
        routes=[RoutingRule(**item) for item in routing_payload.get("routes", [])],
    )
    bundle.validate_references(root_dir)
    return bundle
