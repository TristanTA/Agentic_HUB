from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.models.task import Task
from agentic_hub.models.tool_policy import ToolPolicy
from agentic_hub.models.worker_instance import WorkerInstance


@dataclass
class EffectivePolicy:
    worker_id: str
    tool_ids: List[str] = field(default_factory=list)
    memory_types: List[str] = field(default_factory=list)
    approval_required_tools: List[str] = field(default_factory=list)
    tool_policies: Dict[str, ToolPolicy] = field(default_factory=dict)


class PolicyResolver:
    def __init__(self, worker_registry: WorkerRegistry, tool_registry: ToolRegistry) -> None:
        self.worker_registry = worker_registry
        self.tool_registry = tool_registry

    def resolve_for_worker(self, worker: WorkerInstance) -> EffectivePolicy:
        loadout = self.worker_registry.get_loadout(worker.loadout_id)

        memory_types: list[str] = []
        if loadout.memory_policy_ref:
            memory_policy = self.worker_registry.get_memory_policy(loadout.memory_policy_ref)
            memory_types = list(memory_policy.allowed_memory_types)

        tool_policies: Dict[str, ToolPolicy] = {}
        approval_required_tools: list[str] = []

        for tool_id in loadout.allowed_tool_ids:
            policy = ToolPolicy(
                tool_id=tool_id,
                mode="allow",
                access_level="execute",
            )
            override = loadout.tool_policy_overrides.get(tool_id)
            if isinstance(override, dict):
                policy = ToolPolicy(**{"tool_id": tool_id, **override})
            tool_policies[tool_id] = policy
            if policy.require_approval:
                approval_required_tools.append(tool_id)

        return EffectivePolicy(
            worker_id=worker.worker_id,
            tool_ids=list(loadout.allowed_tool_ids),
            memory_types=memory_types,
            approval_required_tools=approval_required_tools,
            tool_policies=tool_policies,
        )

    def worker_can_handle_task(self, worker: WorkerInstance, task: Task) -> bool:
        worker_type = self.worker_registry.get_type(worker.type_id)
        policy = self.resolve_for_worker(worker)

        if not worker.enabled:
            return False
        if worker.status == "disabled":
            return False
        if worker.health == "failing":
            return False
        if worker_type.allowed_task_kinds and task.kind not in worker_type.allowed_task_kinds:
            return False

        for tool_id in task.required_tool_ids:
            if tool_id not in policy.tool_ids:
                return False
            if not self.tool_registry.has(tool_id):
                return False
            if policy.tool_policies[tool_id].mode == "deny":
                return False

        for memory_type in task.required_memory_types:
            if memory_type not in policy.memory_types:
                return False

        return True

    def task_requires_approval(self, worker: WorkerInstance, task: Task) -> bool:
        if task.approval_required:
            return True

        policy = self.resolve_for_worker(worker)
        for tool_id in task.required_tool_ids:
            tool_policy = policy.tool_policies.get(tool_id)
            if tool_policy and tool_policy.require_approval:
                return True

        return False

