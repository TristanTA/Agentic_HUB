from __future__ import annotations

from shared.schemas import AgentInterface, AgentLifecycleStatus, AgentRole, ModelProfile, ToolProfile
from specs.service import AgentSpecService


def test_spec_service_creates_validates_and_activates_spec(repo_copy):
    service = AgentSpecService(repo_copy)
    spec = service.create_draft(
        agent_id="roadmap_worker",
        purpose="Create direct roadmap outputs.",
        role=AgentRole.PLANNER,
        interface=AgentInterface.INTERNAL,
        autonomy_level="bounded",
        model_profile=ModelProfile.CHEAP,
        tool_profile=ToolProfile.PLANNER,
    )

    assert spec.status == AgentLifecycleStatus.DRAFT

    validation = service.validate_spec(spec.id)
    activated = service.activate_spec(spec.id)
    registry = service.load_runtime_registry()

    assert validation.valid is True
    assert activated.status_after_validation == AgentLifecycleStatus.ACTIVE
    assert spec.id in {item.id for item in registry.agents}


def test_spec_service_explains_missing_and_inactive_visibility(repo_copy):
    service = AgentSpecService(repo_copy)
    missing = service.explain_visibility("missing", runtime_running=False, provider_ready=False)

    spec = service.create_draft(
        agent_id="draft_worker",
        purpose="Draft only worker.",
        role=AgentRole.EXECUTOR,
        interface=AgentInterface.INTERNAL,
        autonomy_level="bounded",
        model_profile=ModelProfile.CHEAP,
        tool_profile=ToolProfile.MINIMAL,
    )
    inactive = service.explain_visibility(spec.id, runtime_running=True, provider_ready=True)

    assert missing["reason"] == "spec missing"
    assert inactive["reason"] == "inactive/disabled"
