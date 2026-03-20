from __future__ import annotations

from hub.agents.factory import AgentFactory
from hub.inputs.normalize import normalize_telegram_payload
from hub.models.providers import ModelRegistry
from hub.registry.loader import load_registries
from shared.schemas import AgentContext


def test_agent_factory_builds_langchain_agent(repo_copy):
    bundle = load_registries(repo_copy)
    spec = bundle.agents["general_assistant"]
    prompt = (repo_copy / spec.prompt_file).read_text(encoding="utf-8")
    skills = [(repo_copy / bundle.skills[skill_id].markdown_file).read_text(encoding="utf-8") for skill_id in spec.skill_ids]
    factory = AgentFactory(ModelRegistry(bundle.models))
    agent = factory.build(spec, prompt, skills)
    context = AgentContext(
        run_id="run-1",
        event=normalize_telegram_payload({"text": "hello"}),
        allowed_tools=spec.allowed_tools,
        model_id=spec.preferred_model,
        prompt_text=prompt,
        resolved_skills=[bundle.skills[skill_id].name for skill_id in spec.skill_ids],
        workspace_path=str(repo_copy / "workspace" / "run-1"),
    )
    result = agent.handle(context, "hello")
    assert spec.id == result.agent_id
    assert "echo" in result.output_text.lower()
