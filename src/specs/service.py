from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from shared.schemas import (
    AgentDefinitionSpec,
    AgentInterface,
    AgentLifecycleStatus,
    AgentRole,
    AgentValidationReport,
    ModelProfile,
    RuntimeAgentEntry,
    RuntimeRegistrySnapshot,
    SkillProfile,
    ToolProfile,
)


def _slugify(value: str) -> str:
    lowered = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    lowered = re.sub(r"[^a-z0-9_]", "", lowered)
    lowered = re.sub(r"_+", "_", lowered).strip("_")
    return lowered


class AgentSpecService:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.specs_dir = root_dir / "agent_specs"
        self.registry_path = root_dir / "generated" / "agent_os_registry.json"
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.rebuild_runtime_registry()

    def list_specs(self) -> list[AgentDefinitionSpec]:
        specs: list[AgentDefinitionSpec] = []
        for path in sorted(self.specs_dir.glob("*.yaml")):
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if payload:
                specs.append(AgentDefinitionSpec(**payload))
        return specs

    def get_spec(self, agent_id: str) -> AgentDefinitionSpec | None:
        path = self.spec_path(agent_id)
        if not path.exists():
            return None
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not payload:
            return None
        return AgentDefinitionSpec(**payload)

    def spec_path(self, agent_id: str) -> Path:
        return self.specs_dir / f"{agent_id}.yaml"

    def create_draft(
        self,
        *,
        agent_id: str,
        purpose: str,
        role: AgentRole,
        interface: AgentInterface,
        autonomy_level: str,
        model_profile: ModelProfile,
        tool_profile: ToolProfile,
        skill_profile: SkillProfile | None = None,
        telegram: dict | None = None,
    ) -> AgentDefinitionSpec:
        normalized_id = _slugify(agent_id)
        spec = AgentDefinitionSpec(
            id=normalized_id,
            purpose=purpose.strip(),
            role=role,
            interface=interface,
            autonomy_level=autonomy_level.strip() or "bounded",
            model_profile=model_profile,
            tool_profile=tool_profile,
            skill_profile=skill_profile or self._default_skill_profile(role),
            status=AgentLifecycleStatus.DRAFT,
            telegram=telegram or {},
        )
        self.save_spec(spec)
        return spec

    def save_spec(self, spec: AgentDefinitionSpec) -> AgentDefinitionSpec:
        spec.updated_at = datetime.now(timezone.utc)
        self.spec_path(spec.id).write_text(
            yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
        return spec

    def validate_spec(self, agent_id: str) -> AgentValidationReport:
        spec = self.get_spec(agent_id)
        if spec is None:
            return AgentValidationReport(
                agent_id=agent_id,
                valid=False,
                errors=[f"Spec {agent_id} does not exist."],
                status_after_validation=AgentLifecycleStatus.BROKEN,
            )
        errors: list[str] = []
        warnings: list[str] = []
        if not spec.id or spec.id != _slugify(spec.id):
            errors.append("id must be lowercase letters, numbers, or underscores.")
        if not spec.purpose.strip():
            errors.append("purpose is required.")
        if spec.interface == AgentInterface.TELEGRAM and not str(spec.telegram.get("bot_token_env", "")).strip():
            errors.append("telegram interface requires telegram.bot_token_env.")
        if spec.role == AgentRole.SUPERVISOR:
            warnings.append("supervisor role is reserved; Vanta Core is outside the runtime.")
        if errors:
            status_after = AgentLifecycleStatus.BROKEN
            spec.status = AgentLifecycleStatus.BROKEN
        elif spec.status == AgentLifecycleStatus.ACTIVE:
            status_after = AgentLifecycleStatus.ACTIVE
        else:
            status_after = AgentLifecycleStatus.VALIDATED
            spec.status = AgentLifecycleStatus.VALIDATED
        self.save_spec(spec)
        return AgentValidationReport(
            agent_id=spec.id,
            valid=not errors,
            errors=errors,
            warnings=warnings,
            status_after_validation=status_after,
        )

    def activate_spec(self, agent_id: str) -> AgentValidationReport:
        report = self.validate_spec(agent_id)
        if not report.valid:
            return report
        spec = self.get_spec(agent_id)
        assert spec is not None
        spec.status = AgentLifecycleStatus.ACTIVE
        self.save_spec(spec)
        self.rebuild_runtime_registry()
        return AgentValidationReport(
            agent_id=spec.id,
            valid=True,
            errors=[],
            warnings=report.warnings,
            status_after_validation=AgentLifecycleStatus.ACTIVE,
        )

    def deactivate_spec(self, agent_id: str) -> AgentDefinitionSpec | None:
        spec = self.get_spec(agent_id)
        if spec is None:
            return None
        spec.status = AgentLifecycleStatus.DISABLED
        self.save_spec(spec)
        self.rebuild_runtime_registry()
        return spec

    def rebuild_runtime_registry(self) -> RuntimeRegistrySnapshot:
        entries = [
            self._to_runtime_entry(spec)
            for spec in self.list_specs()
            if spec.status == AgentLifecycleStatus.ACTIVE
        ]
        snapshot = RuntimeRegistrySnapshot(agents=entries)
        self.registry_path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        return snapshot

    def load_runtime_registry(self) -> RuntimeRegistrySnapshot:
        if not self.registry_path.exists():
            return RuntimeRegistrySnapshot()
        payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        return RuntimeRegistrySnapshot(**payload)

    def explain_visibility(self, agent_id: str, *, runtime_running: bool, provider_ready: bool) -> dict:
        spec = self.get_spec(agent_id)
        if spec is None:
            return {"agent_id": agent_id, "visible": False, "reason": "spec missing"}
        report = self.validate_spec(agent_id)
        if not report.valid:
            return {"agent_id": agent_id, "visible": False, "reason": "validation failed", "errors": report.errors}
        if spec.status in {AgentLifecycleStatus.DRAFT, AgentLifecycleStatus.DISABLED, AgentLifecycleStatus.BROKEN}:
            return {"agent_id": agent_id, "visible": False, "reason": "inactive/disabled", "status": spec.status.value}
        if not provider_ready and spec.model_profile != ModelProfile.CHEAP:
            return {"agent_id": agent_id, "visible": False, "reason": "provider unavailable"}
        if not runtime_running:
            return {"agent_id": agent_id, "visible": False, "reason": "runtime unavailable"}
        registry = self.load_runtime_registry()
        if agent_id not in {item.id for item in registry.agents}:
            return {"agent_id": agent_id, "visible": False, "reason": "runtime registry stale"}
        return {"agent_id": agent_id, "visible": True, "reason": "agent active and reachable"}

    def _to_runtime_entry(self, spec: AgentDefinitionSpec) -> RuntimeAgentEntry:
        return RuntimeAgentEntry(
            id=spec.id,
            purpose=spec.purpose,
            role=spec.role,
            interface=spec.interface,
            model_id=self._model_id_for_profile(spec.model_profile),
            tool_profile=spec.tool_profile,
            skill_profile=spec.skill_profile,
            system_prompt=self._system_prompt_for_spec(spec),
            permissions=spec.permissions,
        )

    def _model_id_for_profile(self, profile: ModelProfile) -> str:
        if profile == ModelProfile.STRONG:
            return "openai_gpt5_vanta"
        if profile == ModelProfile.CHEAP:
            return "echo_model"
        return "openai_gpt5_mini"

    def _default_skill_profile(self, role: AgentRole) -> SkillProfile:
        if role == AgentRole.PLANNER:
            return SkillProfile.PLANNING
        if role in {AgentRole.OPERATOR, AgentRole.SUPERVISOR}:
            return SkillProfile.OPERATOR
        return SkillProfile.GENERAL

    def _system_prompt_for_spec(self, spec: AgentDefinitionSpec) -> str:
        return "\n".join(
            [
                f"You are {spec.id}.",
                f"Purpose: {spec.purpose}",
                f"Role: {spec.role.value}",
                f"Interface: {spec.interface.value}",
                "Operate directly and concisely.",
                "Return useful output without unnecessary commentary.",
            ]
        )
