from agentic_hub.core.memory_manager import MemoryManager
from agentic_hub.models.memory_records import RunEpisode, SemanticFact, SessionEpisode


def test_memory_manager_builds_context():
    manager = MemoryManager()
    manager.start_run("run1", {"task": "hello"})
    manager.save_session_episode(
        SessionEpisode(
            session_id="session1",
            summary="Recent session summary.",
        )
    )
    manager.upsert_semantic_fact(
        SemanticFact(
            key="band_name",
            value="New Name",
        )
    )

    bundle = manager.build_context_bundle(
        run_id="run1",
        session_id="session1",
        semantic_keys=["band_name"],
    )

    assert bundle["working_memory"]["task"] == "hello"
    assert bundle["session_episode"].summary == "Recent session summary."
    assert bundle["semantic_memory"]["band_name"] == "New Name"


def test_semantic_fact_supersedes_old_value():
    manager = MemoryManager()
    manager.upsert_semantic_fact(SemanticFact(key="band_name", value="Old Name"))
    manager.upsert_semantic_fact(SemanticFact(key="band_name", value="New Name"))

    active = manager.get_active_semantic_fact("band_name")
    history = manager.get_semantic_history("band_name")

    assert active is not None
    assert active.value == "New Name"
    assert any(item.status == "superseded" for item in history)

