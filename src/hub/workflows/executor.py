from __future__ import annotations

from hub.agents.factory import HubAgent
from hub.collaboration.workspace import MarkdownWorkspace
from shared.schemas import AgentContext, WorkflowResult, WorkflowSpec
from storage.files.repository import FileRepository


class WorkflowExecutor:
    def __init__(
        self,
        workspace: MarkdownWorkspace,
        file_repo: FileRepository,
        agents: dict[str, HubAgent],
    ) -> None:
        self.workspace = workspace
        self.file_repo = file_repo
        self.agents = agents

    def run(self, context: AgentContext, workflow_spec: WorkflowSpec) -> WorkflowResult:
        latest_text = context.event.text
        last_task_id: str | None = None
        for step in workflow_spec.steps:
            if step.type.value == "agent" and step.target_id:
                latest_text = self.agents[step.target_id].handle(context, latest_text).output_text
            elif step.type.value == "markdown_task" and step.source_agent and step.target_agent and step.intent:
                last_task_id = self.workspace.create_task(
                    source_agent=step.source_agent,
                    target_agent=step.target_agent,
                    intent=step.intent,
                    input_context=latest_text,
                )
            elif step.type.value == "agent_task" and step.target_id and last_task_id:
                task_md = self.file_repo.read_markdown(f"workspace/agent_tasks/{last_task_id}.md")
                latest_text = self.agents[step.target_id].handle(context, task_md).output_text
                self.workspace.complete_task(last_task_id, step.target_id, latest_text)
        return WorkflowResult(workflow_id=workflow_spec.id, status="completed", final_text=latest_text)
