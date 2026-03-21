from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from hub.adapters.registry import AdapterRegistry, build_adapter
from hub.agents.factory import AgentFactory, HubAgent
from hub.collaboration.workspace import MarkdownWorkspace
from hub.models.providers import ModelRegistry
from hub.outputs.telegram import TelegramOutputAdapter
from hub.registry.loader import RegistryBundle, load_registries
from hub.router.router import DeterministicRouter
from hub.tasks.service import TaskService
from hub.tools.builtin import build_builtin_tools
from hub.workflows.executor import WorkflowExecutor
from shared.schemas import AgentContext, RouteDecision, RunTrace, TargetType
from storage.files.repository import FileRepository
from storage.sqlite.db import SQLiteStore

from .logging import StructuredLogger


class HubRuntime:
    def __init__(self, root_dir: Path, bundle: RegistryBundle) -> None:
        self.root_dir = root_dir
        self.bundle = bundle
        hub_cfg = bundle.hub_config.hub
        self.file_repo = FileRepository(root_dir)
        self.store = SQLiteStore(root_dir / hub_cfg.sqlite_path)
        self.logger = StructuredLogger(root_dir / hub_cfg.structured_log_path, root_dir / hub_cfg.human_log_path)
        self.router = DeterministicRouter(bundle.routes)
        self.workspace = MarkdownWorkspace(self.file_repo)
        self.model_registry = ModelRegistry(bundle.models)
        self.agent_factory = AgentFactory(self.model_registry)
        self.telegram_output = TelegramOutputAdapter(enabled=bundle.hub_config.telegram.enabled)
        self.state_path = root_dir / hub_cfg.state_path
        self.pid_path = root_dir / hub_cfg.pid_path
        self.agents = self._build_agents()
        self.adapters = self._build_adapters()
        self.task_service = TaskService(self.store, self.adapters)
        self.built_tools = build_builtin_tools(self.file_repo, self.store, self.telegram_output, self)
        self.workflows = {
            workflow.id: WorkflowExecutor(self.workspace, self.file_repo, self.agents)
            for workflow in bundle.workflows.values()
            if workflow.enabled
        }
        self._write_state("running")

    def reload_config(self) -> None:
        self.bundle = load_registries(self.root_dir)
        hub_cfg = self.bundle.hub_config.hub
        self.router = DeterministicRouter(self.bundle.routes)
        self.model_registry = ModelRegistry(self.bundle.models)
        self.agent_factory = AgentFactory(self.model_registry)
        self.telegram_output = TelegramOutputAdapter(enabled=self.bundle.hub_config.telegram.enabled)
        self.state_path = self.root_dir / hub_cfg.state_path
        self.pid_path = self.root_dir / hub_cfg.pid_path
        self.agents = self._build_agents()
        self.adapters = self._build_adapters()
        self.task_service = TaskService(self.store, self.adapters)
        self.built_tools = build_builtin_tools(self.file_repo, self.store, self.telegram_output, self)
        self.workflows = {
            workflow.id: WorkflowExecutor(self.workspace, self.file_repo, self.agents)
            for workflow in self.bundle.workflows.values()
            if workflow.enabled
        }

    def _build_agents(self) -> dict[str, HubAgent]:
        agents: dict[str, HubAgent] = {}
        for spec in self.bundle.agents.values():
            if not spec.enabled:
                continue
            prompt_text = self.file_repo.read_text(spec.prompt_file)
            if spec.soul_file:
                soul_text = self.file_repo.read_text(spec.soul_file)
                prompt_text = f"{soul_text}\n\n{prompt_text}"
            skills = [self.file_repo.read_text(self.bundle.skills[skill_id].markdown_file) for skill_id in spec.skill_ids]
            agents[spec.id] = self.agent_factory.build(spec, prompt_text, skills)
        return agents

    def _write_state(self, status: str) -> None:
        payload = {"status": status, "updated_at": time.time()}
        self.file_repo.write_state(str(self.state_path.relative_to(self.root_dir)), payload)

    def _build_adapters(self) -> AdapterRegistry:
        registry = AdapterRegistry()
        for spec in self.bundle.agents.values():
            if not spec.enabled:
                continue
            hub_agent = self.agents.get(spec.id)
            adapter = build_adapter(
                spec,
                hub_agent=hub_agent,
                store=self.store,
                context_factory=self._build_task_context,
            )
            registry.register(spec.id, adapter)
        return registry

    def is_paused(self) -> bool:
        if not self.state_path.exists():
            return False
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        return payload.get("status") == "paused"

    def process_event(self, event) -> dict:
        if self.is_paused():
            return {"status": "paused"}
        start = time.perf_counter()
        run_id = str(uuid.uuid4())
        decision = self.router.route(event)
        context = self._build_context(run_id, event, decision)
        result_text = self._execute(decision, context)
        latency_ms = int((time.perf_counter() - start) * 1000)
        trace = RunTrace(
            run_id=run_id,
            route=decision,
            prompt_files=[self.bundle.agents[decision.target_id].prompt_file] if decision.target_id in self.bundle.agents else [],
            skill_files=[
                self.bundle.skills[skill_id].markdown_file
                for skill_id in self.bundle.agents[decision.target_id].skill_ids
            ]
            if decision.target_id in self.bundle.agents
            else [],
            outputs=[result_text],
            latency_ms=latency_ms,
        )
        self.store.write_run_trace(trace)
        self.store.write_health_snapshot("ok", {"last_run_id": run_id})
        self.logger.log(
            "hub.run_completed",
            {
                "run_id": run_id,
                "route": decision.model_dump(),
                "latency_ms": latency_ms,
                "prompt_files": trace.prompt_files,
                "skill_files": trace.skill_files,
            },
        )
        self.telegram_output.send({"thread_id": event.thread_id, "text": result_text})
        return {"run_id": run_id, "output_text": result_text, "route": decision.model_dump()}

    def process_event_for_agent(self, event, agent_id: str, output_adapter: TelegramOutputAdapter | None = None) -> dict:
        if self.is_paused():
            return {"status": "paused"}
        run_id = str(uuid.uuid4())
        if agent_id not in self.bundle.agents:
            raise ValueError(f"Unknown agent {agent_id}")
        decision = RouteDecision(
            matched_rule=f"direct:{agent_id}",
            target_type=TargetType.AGENT,
            target_id=agent_id,
            reason="Direct agent runner",
            config_version="v1",
        )
        context = self._build_context(run_id, event, decision)
        result_text = self._execute(decision, context)
        (output_adapter or self.telegram_output).send({"thread_id": event.thread_id, "text": result_text})
        return {"run_id": run_id, "output_text": result_text, "route": decision.model_dump()}

    def _build_context(self, run_id: str, event, decision: RouteDecision) -> AgentContext:
        agent_id = decision.target_id if decision.target_id in self.bundle.agents else self.bundle.hub_config.hub.default_agent
        agent = self.bundle.agents[agent_id]
        prompt_text = self.file_repo.read_text(agent.prompt_file)
        if agent.soul_file:
            soul_text = self.file_repo.read_text(agent.soul_file)
            prompt_text = f"{soul_text}\n\n{prompt_text}"
        return AgentContext(
            run_id=run_id,
            event=event,
            allowed_tools=agent.allowed_tools,
            model_id=agent.preferred_model,
            prompt_text=prompt_text,
            resolved_skills=[self.bundle.skills[skill_id].name for skill_id in agent.skill_ids],
            workspace_path=str((self.root_dir / "workspace" / run_id).resolve()),
            agent_id=agent_id,
        )

    def _build_task_context(self, agent_id: str, goal: str, input_context: str) -> AgentContext:
        event_payload = {
            "text": input_context,
            "thread_id": f"task:{agent_id}",
            "message": {"text": input_context, "chat": {"id": f"task:{agent_id}"}, "message_id": str(uuid.uuid4())},
        }
        decision = RouteDecision(
            matched_rule=f"task:{agent_id}",
            target_type=TargetType.AGENT,
            target_id=agent_id,
            reason=goal,
            config_version="v1",
        )
        from hub.inputs.normalize import normalize_telegram_payload

        return self._build_context(str(uuid.uuid4()), normalize_telegram_payload(event_payload), decision)

    def list_agent_profiles(self) -> list[dict]:
        profiles = []
        for spec in self.bundle.agents.values():
            profiles.append(
                {
                    "id": spec.id,
                    "purpose": spec.purpose,
                    "exposure_mode": spec.exposure_mode.value,
                    "execution_mode": spec.execution_mode.value,
                    "adapter_type": getattr(spec.adapter_type, "value", spec.adapter_type),
                    "enabled": spec.enabled,
                    "telegram": spec.telegram,
                }
            )
        return sorted(profiles, key=lambda item: item["id"])

    def _execute(self, decision: RouteDecision, context: AgentContext) -> str:
        if decision.target_type == TargetType.AGENT:
            spec = self.bundle.agents[decision.target_id]
            if spec.execution_mode.value != "native_hub":
                adapter = self.adapters.get(spec.id)
                if adapter is None:
                    raise ValueError(f"No adapter registered for {spec.id}")
                result = adapter.send_message(context.event.text, thread_id=context.event.thread_id)
                return json.dumps(result)
            if self.model_registry.supports_function_tools(spec.preferred_model) and spec.allowed_tools:
                return self._execute_agent_with_tools(spec, context)
            return self.agents[decision.target_id].handle(context, context.event.text).output_text
        if decision.target_type == TargetType.WORKFLOW:
            workflow = self.bundle.workflows[decision.target_id]
            return self.workflows[workflow.id].run(context, workflow).final_text
        if decision.target_type == TargetType.TOOL:
            return json.dumps(self.built_tools[decision.target_id].invoke(context, {}).output)
        raise ValueError(f"Unsupported target type: {decision.target_type}")

    def _execute_agent_with_tools(self, spec, context: AgentContext) -> str:
        system_prompt = context.prompt_text
        skill_blocks = [
            self.file_repo.read_text(self.bundle.skills[skill_id].markdown_file)
            for skill_id in spec.skill_ids
        ]
        if skill_blocks:
            system_prompt = f"{system_prompt}\n\n" + "\n\n".join(skill_blocks)

        tool_defs = []
        for tool_id in spec.allowed_tools:
            tool_spec = self.bundle.tools.get(tool_id)
            builtin = self.built_tools.get(tool_id)
            if tool_spec is None or builtin is None:
                continue
            tool_defs.append(
                {
                    "type": "function",
                    "name": tool_id,
                    "description": tool_spec.description,
                    "parameters": tool_spec.input_schema or {"type": "object", "properties": {}},
                }
            )

        def execute_tool(tool_name: str, tool_input: dict) -> dict:
            tool = self.built_tools.get(tool_name)
            if tool is None:
                return {"ok": False, "error": f"Unknown tool {tool_name}"}
            result = tool.invoke(context, tool_input)
            if result.success:
                return result.output
            return {"ok": False, "error": result.error or "tool_failed"}

        return self.model_registry.run_with_tools(
            model_id=spec.preferred_model,
            system_prompt=system_prompt,
            user_input=context.event.text,
            tools=tool_defs,
            tool_executor=execute_tool,
        )
