from hub.dead_task_store import DeadTaskStore
from hub.tasks import DeadTaskRecord, utc_now


def test_dead_task_store_append_and_load(tmp_path):
    dead_file = tmp_path / "dead_tasks.json"
    store = DeadTaskStore(dead_file)

    record_1 = DeadTaskRecord(
        task_data={
            "id": "task-1",
            "name": "Broken Task",
            "handler_name": "interval_task",
            "retry_count": 4,
        },
        failed_at=utc_now(),
        reason="final failure 1",
        retry_count=4,
    )

    record_2 = DeadTaskRecord(
        task_data={
            "id": "task-2",
            "name": "Also Broken",
            "handler_name": "startup_task",
            "retry_count": 2,
        },
        failed_at=utc_now(),
        reason="final failure 2",
        retry_count=2,
    )

    store.append(record_1)
    store.append(record_2)

    loaded = store.load()

    assert len(loaded) == 2
    assert loaded[0].task_data["id"] == "task-1"
    assert loaded[0].reason == "final failure 1"
    assert loaded[0].retry_count == 4

    assert loaded[1].task_data["id"] == "task-2"
    assert loaded[1].reason == "final failure 2"
    assert loaded[1].retry_count == 2


def test_dead_task_store_load_missing_file_returns_empty_list(tmp_path):
    dead_file = tmp_path / "missing_dead_tasks.json"
    store = DeadTaskStore(dead_file)

    loaded = store.load()

    assert loaded == []