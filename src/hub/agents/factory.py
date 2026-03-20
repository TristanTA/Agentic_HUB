from __future__ import annotations

from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate

from hub.models.providers import ModelRegistry
from shared.schemas import AgentContext, AgentResult, AgentSpec


@dataclass(slots=True)
class HubAgent:
    spec: AgentSpec
    chain: object

    def handle(self, context: AgentContext, event_or_task: str) -> AgentResult:
        response = self.chain.invoke({"input": event_or_task})
        return AgentResult(
            agent_id=self.spec.id,
            output_text=str(response),
            metadata={"skills": context.resolved_skills},
        )


class AgentFactory:
    def __init__(self, model_registry: ModelRegistry) -> None:
        self.model_registry = model_registry

    def build(self, spec: AgentSpec, resolved_prompt: str, resolved_skills: list[str]) -> HubAgent:
        skill_block = "\n\n".join(resolved_skills)
        prompt = ChatPromptTemplate.from_template(
            "{system_prompt}\n\n{skill_block}\n\nUser/Input:\n{input}"
        ).partial(system_prompt=resolved_prompt, skill_block=skill_block)
        model = self.model_registry.build_runnable(spec.preferred_model)
        chain = prompt | model
        return HubAgent(spec=spec, chain=chain)
