from agent_os_starter_v2.registries.tool_registry import ToolRegistry
from agent_os_starter_v2.registries.worker_registry import WorkerRegistry
from agent_os_starter_v2.schemas.loadout import Loadout
from agent_os_starter_v2.schemas.memory_policy import MemoryPolicy
from agent_os_starter_v2.schemas.tool_definition import ToolDefinition
from agent_os_starter_v2.schemas.worker_instance import WorkerInstance
from agent_os_starter_v2.schemas.worker_role import WorkerRole
from agent_os_starter_v2.schemas.worker_type import WorkerType


def build_example() -> tuple[ToolRegistry, WorkerRegistry]:
    tool_registry = ToolRegistry()
    worker_registry = WorkerRegistry()

    tool_registry.register(
        ToolDefinition(
            tool_id="telegram_send_message",
            name="Telegram Send Message",
            description="Send a Telegram message to a configured chat or user.",
            capability_tags=["messaging", "telegram"],
            implementation_ref="tools.telegram.send_message",
            safety_level="low",
        )
    )

    tool_registry.register(
        ToolDefinition(
            tool_id="web_search",
            name="Web Search",
            description="Search the public web for current information.",
            capability_tags=["search", "research"],
            implementation_ref="tools.web.search",
            safety_level="low",
        )
    )

    worker_registry.register_type(
        WorkerType(
            type_id="agent_worker",
            name="Agent Worker",
            execution_mode="llm",
            can_use_tools=True,
            can_spawn_tasks=True,
            can_request_approval=True,
            allowed_task_kinds=["research", "message", "plan"],
        )
    )

    worker_registry.register_role(
        WorkerRole(
            role_id="operator",
            name="Operator",
            purpose="Execute approved actions and help move work forward.",
            behavior_guide_ref="guides/operator.md",
            default_output_style="concise",
        )
    )

    worker_registry.register_memory_policy(
        MemoryPolicy(
            policy_id="aria_memory",
            allowed_memory_types=["working", "episodic", "semantic"],
            retrieval_limits={"episodic": 10, "semantic": 8},
            allowed_tags=["music", "band", "preferences"],
            write_permissions={"working": True, "episodic": True, "semantic": False},
            promotion_rules_ref="memory/promote_user_preferences.yaml",
        )
    )

    worker_registry.register_loadout(
        Loadout(
            loadout_id="aria_v1",
            name="Aria v1",
            description="Starter operator loadout for Aria.",
            prompt_refs=["prompts/aria_system.md"],
            soul_ref="souls/aria.md",
            skill_refs=["skills/recommend_songs.md"],
            memory_policy_ref="aria_memory",
            allowed_tool_ids=["telegram_send_message", "web_search"],
            tags=["music", "operator"],
        )
    )

    worker_registry.register_worker(
        WorkerInstance(
            worker_id="aria",
            name="Aria",
            type_id="agent_worker",
            role_id="operator",
            loadout_id="aria_v1",
            owner="tristan",
            assigned_queues=["default"],
            tags=["music", "assistant"],
        )
    )

    worker_registry.validate_worker_refs("aria")
    return tool_registry, worker_registry


if __name__ == "__main__":
    tools, workers = build_example()
    print("Registered tools:")
    for tool in tools.list_all():
        print(f"- {tool.tool_id}")

    print("\nRegistered workers:")
    for worker in workers.list_workers():
        print(f"- {worker.worker_id} ({worker.type_id} / {worker.role_id} / {worker.loadout_id})")
