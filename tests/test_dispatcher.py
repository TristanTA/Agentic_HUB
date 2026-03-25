from hub.dispatcher import Dispatcher
from hub.policy_resolver import PolicyResolver
from registries.tool_registry import ToolRegistry
from registries.worker_registry import WorkerRegistry
from schemas.loadout import Loadout
from schemas.memory_policy import MemoryPolicy
from schemas.task import Task
from schemas.tool_definition import ToolDefinition
from schemas.worker_instance import WorkerInstance
from schemas.worker_role import WorkerRole
from schemas.worker_type import WorkerType


def build_fixture():
    tool_registry = ToolRegistry()
    worker_registry = WorkerRegistry()

    tool_registry.register(
        ToolDefinition(
            tool_id="telegram_send_message",
            name="Telegram",
            description="Send a telegram message.",
            implementation_ref="hub.tools.telegram_tools.send_message",
        )
    )

    worker_registry.register_type(
        WorkerType(
            type_id="agent_worker",
            name="Agent Worker",
            execution_mode="llm",
            allowed_task_kinds=["message"],
        )
    )

    worker_registry.register_role(
        WorkerRole(
            role_id="operator",
            name="Operator",
            purpose="Execute actions.",
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
        )
    )

    worker_registry.register_worker(
        WorkerInstance(
            worker_id="aria",
            name="Aria",
            type_id="agent_worker",
            role_id="operator",
            loadout_id="operator_loadout",
            priority_bias=5,
        )
    )

    resolver = PolicyResolver(worker_registry, tool_registry)
    dispatcher = Dispatcher(worker_registry, resolver)
    return dispatcher


def test_select_worker_returns_matching_worker():
    dispatcher = build_fixture()

    task = Task(
        task_id="1",
        kind="message",
        required_tool_ids=["telegram_send_message"],
    )

    worker = dispatcher.select_worker(task)
    assert worker is not None
    assert worker.worker_id == "aria"
