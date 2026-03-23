from __future__ import annotations

from agent_os.runtime import AgentOSRuntime
from shared.schemas import AgentInterface, AgentRole, ModelProfile, ToolProfile
from specs.service import AgentSpecService


def test_agent_os_runtime_executes_active_cheap_agent(repo_copy):
    specs = AgentSpecService(repo_copy)
    specs.create_draft(
        agent_id="echo_worker",
        purpose="Echo-style worker.",
        role=AgentRole.EXECUTOR,
        interface=AgentInterface.INTERNAL,
        autonomy_level="bounded",
        model_profile=ModelProfile.CHEAP,
        tool_profile=ToolProfile.MINIMAL,
    )
    specs.activate_spec("echo_worker")

    runtime = AgentOSRuntime(repo_copy)
    result = runtime.execute("echo_worker", "run this task")

    assert result["agent_id"] == "echo_worker"
    assert "run this task" in result["output_text"]


def test_agent_os_runtime_status_reads_generated_registry(repo_copy):
    runtime = AgentOSRuntime(repo_copy)
    status = runtime.status()

    assert status["running"] is False
    assert "echo_worker" in status["active_agents"]
