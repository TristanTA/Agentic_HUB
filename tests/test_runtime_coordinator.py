from hub.runtime_coordinator import RuntimeCoordinator
from hub.legacy_worker_adapter import LegacyHandlerAdapter
from registries.tool_registry import ToolRegistry
from registries.worker_registry import WorkerRegistry
from schemas.loadout import Loadout
from schemas.memory_policy import MemoryPolicy
from schemas.task import Task
from schemas.tool_definition import ToolDefinition
from schemas.worker_instance import WorkerInstance
from schemas.worker_role import WorkerRole
from schemas.worker_type import WorkerType


class DummyLogger:
    def error(self, *args, **kwargs):
        return None


def build_fixture():
    tools = ToolRegistry()
    workers = WorkerRegistry()

    tools.register(
        ToolDefinition(
            tool_id="telegram_send_message",
            name="Telegram",
            description="Send telegram message",
            implementation_ref="hub.tools.telegram_tools.send_message",
        )
    )

    workers.register_type(
        WorkerType(
            type_id="tool_worker",
            name="Tool Worker",
            execution_mode="deterministic",
            allowed_task_kinds=["send_message"],
        )
    )
    workers.register_role(
        WorkerRole(
            role_id="operator",
            name="Operator",
            purpose="Execute actions",
        )
    )
    workers.register_memory_policy(
        MemoryPolicy(
            policy_id="basic_memory",
            allowed_memory_types=["working", "episodic"],
        )
    )
    workers.register_loadout(
        Loadout(
            loadout_id="operator_loadout",
            name="Operator Loadout",
            memory_policy_ref="basic_memory",
            allowed_tool_ids=["telegram_send_message"],
        )
    )
    workers.register_worker(
        WorkerInstance(
            worker_id="messenger_1",
            name="Messenger 1",
            type_id="tool_worker",
            role_id="operator",
            loadout_id="operator_loadout",
        )
    )

    runtime = RuntimeCoordinator(workers, tools)
    runtime.register_adapter(
        "tool_worker",
        LegacyHandlerAdapter(
            handlers={
                "send_message": lambda payload: {"sent": True, "chat_id": payload.get("chat_id")}
            },
            logger=DummyLogger(),
        ),
    )
    return runtime


def test_runtime_dispatch_task():
    runtime = build_fixture()
    result = runtime.dispatch_task(
        Task(
            task_id="t1",
            kind="send_message",
            payload={"chat_id": 123},
            required_tool_ids=["telegram_send_message"],
        )
    )

    assert result.status == "done"
    assert result.output_payload["result"]["sent"] is True
