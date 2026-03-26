from agentic_hub.core.approval_manager import ApprovalManager
from agentic_hub.core.artifact_store import ArtifactStore
from agentic_hub.core.event_log import EventLog
from agentic_hub.core.policy_resolver import PolicyResolver
from agentic_hub.core.worker_runner import WorkerRunner
from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.models.loadout import Loadout
from agentic_hub.models.memory_policy import MemoryPolicy
from agentic_hub.models.task import Task
from agentic_hub.models.task_result import TaskResult
from agentic_hub.models.tool_definition import ToolDefinition
from agentic_hub.models.worker_instance import WorkerInstance
from agentic_hub.models.worker_role import WorkerRole
from agentic_hub.models.worker_type import WorkerType


class DummyAdapter:
    def run(self, worker, task):
        return TaskResult(
            task_id=task.task_id,
            worker_id=worker.worker_id,
            status="done",
            summary="Completed",
        )


def build_fixture(require_approval: bool = False):
    tool_registry = ToolRegistry()
    worker_registry = WorkerRegistry()

    tool_registry.register(
        ToolDefinition(
            tool_id="telegram_send_message",
            name="Telegram",
            description="Send message",
            implementation_ref="agentic_hub.services.telegram.tools.send_message",
        )
    )

    worker_registry.register_type(
        WorkerType(
            type_id="agent_worker",
            name="Agent",
            execution_mode="llm",
            allowed_task_kinds=["message"],
        )
    )
    worker_registry.register_role(
        WorkerRole(
            role_id="operator",
            name="Operator",
            purpose="Execute actions",
        )
    )
    worker_registry.register_memory_policy(
        MemoryPolicy(
            policy_id="basic_memory",
            allowed_memory_types=["working", "episodic"],
        )
    )
    worker_registry.register_loadout(
        Loadout(
            loadout_id="operator_loadout",
            name="Operator Loadout",
            allowed_tool_ids=["telegram_send_message"],
            memory_policy_ref="basic_memory",
            tool_policy_overrides={
                "telegram_send_message": {
                    "mode": "allow",
                    "access_level": "execute",
                    "require_approval": require_approval,
                }
            },
        )
    )
    worker_registry.register_worker(
        WorkerInstance(
            worker_id="aria",
            name="Aria",
            type_id="agent_worker",
            role_id="operator",
            loadout_id="operator_loadout",
        )
    )

    policy_resolver = PolicyResolver(worker_registry, tool_registry)
    return worker_registry, policy_resolver


def test_worker_runner_executes_without_approval():
    worker_registry, policy_resolver = build_fixture(require_approval=False)
    runner = WorkerRunner(
        policy_resolver=policy_resolver,
        approval_manager=ApprovalManager(),
        artifact_store=ArtifactStore(),
        event_log=EventLog(),
    )

    worker = worker_registry.get_worker("aria")
    task = Task(
        task_id="t1",
        kind="message",
        required_tool_ids=["telegram_send_message"],
    )
    result = runner.run(DummyAdapter(), worker, task)

    assert result.status == "done"


def test_worker_runner_pauses_for_approval():
    worker_registry, policy_resolver = build_fixture(require_approval=True)
    approval_manager = ApprovalManager()
    artifact_store = ArtifactStore()
    runner = WorkerRunner(
        policy_resolver=policy_resolver,
        approval_manager=approval_manager,
        artifact_store=artifact_store,
        event_log=EventLog(),
    )

    worker = worker_registry.get_worker("aria")
    task = Task(
        task_id="t2",
        kind="message",
        required_tool_ids=["telegram_send_message"],
    )
    result = runner.run(DummyAdapter(), worker, task)

    assert result.status == "needs_approval"
    assert approval_manager.get_request_for_task("t2") is not None
    assert len(artifact_store.list_for_task("t2")) == 1


