from __future__ import annotations

from hub.inputs.normalize import normalize_telegram_payload
from hub.main import build_runtime
from shared.schemas import RouteDecision, TargetType


def test_vanta_session_memory_carries_recent_thread_context(repo_copy):
    runtime = build_runtime(repo_copy)
    thread_id = "123"

    first = normalize_telegram_payload(
        {"message": {"message_id": 1, "chat": {"id": thread_id}, "text": "I am working on the wedding venue shortlist."}}
    )
    runtime.process_event_for_agent(first, "vanta_manager", output_adapter=runtime.telegram_output.__class__(enabled=False))

    second = normalize_telegram_payload(
        {"message": {"message_id": 2, "chat": {"id": thread_id}, "text": "The budget is 15k."}}
    )
    runtime.process_event_for_agent(second, "vanta_manager", output_adapter=runtime.telegram_output.__class__(enabled=False))
    context = runtime._build_context(
        "test-run",
        second,
        RouteDecision(
            matched_rule="direct:vanta_manager",
            target_type=TargetType.AGENT,
            target_id="vanta_manager",
            reason="test",
            config_version="v1",
        ),
    )

    assert "wedding venue shortlist" in context.conversation_history
    assert "The budget is 15k." in context.conversation_history


def test_vanta_stores_preference_and_working_state(repo_copy):
    runtime = build_runtime(repo_copy)
    thread_id = "456"

    event = normalize_telegram_payload(
        {"message": {"message_id": 1, "chat": {"id": thread_id}, "text": "Please challenge me hard and ask fewer low-value questions."}}
    )
    runtime.process_event_for_agent(event, "vanta_manager", output_adapter=runtime.telegram_output.__class__(enabled=False))

    memories = runtime.store.list_memory_items(agent_id="vanta_manager", kind="preference", thread_id=thread_id, limit=10)
    state = runtime.store.get_thread_working_state(thread_id=thread_id, agent_id="vanta_manager")

    assert memories
    assert any("challenge me hard" in item.value.lower() for item in memories)
    assert state is not None
    assert state.resolved_information
