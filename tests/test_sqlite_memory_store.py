from pathlib import Path

from agentic_hub.core.sqlite_memory_store import SQLiteMemoryStore
from agentic_hub.models.memory_records import RunEpisode, SemanticFact


def test_sqlite_memory_store_round_trip(tmp_path: Path):
    db_path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(db_path)

    store.save_run_episode(
        RunEpisode(
            run_id="r1",
            worker_id="aria",
            task_id="t1",
            objective="Test run",
            actions_summary="Did a thing",
            outcome="done",
        )
    )

    episode = store.get_run_episode("r1")
    assert episode is not None
    assert episode.objective == "Test run"

    store.upsert_semantic_fact(SemanticFact(key="band_name", value="New Name"))
    fact = store.get_active_semantic_fact("band_name")
    assert fact is not None
    assert fact.value == "New Name"

