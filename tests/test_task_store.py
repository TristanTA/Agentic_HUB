from datetime import timedelta

from hub.task_store import TaskStore
from hub.tasks import Task, utc_now


def test_task_store_save_and_load_round_trip(tmp_path):
    task_file = tmp_path / "tasks.json"
    store = TaskStore(task_file)

    now = utc_now()

    tasks = [
        Task(
            id="task-1",
            name="Startup Task",
            handler_name="startup_task",
            priority=1,
            trigger="startup",
        ),
        Task(
            id="task-2",
            name="Interval Task",
            handler_name="interval_task",
            priority=2,
            trigger="interval",
            interval_seconds=30,
            next_run_at=now,
            last_run_at=now + timedelta(seconds=5),
            last_status="success",
            last_error=None,
            retry_count=1,
            max_retries=3,
            retry_delay_seconds=10,
            payload={"x": 1},
        ),
    ]

    store.save(tasks)
    loaded = store.load()

    assert len(loaded) == 2

    assert loaded[0].id == "task-1"
    assert loaded[0].trigger == "startup"
    assert loaded[0].next_run_at is None

    assert loaded[1].id == "task-2"
    assert loaded[1].trigger == "interval"
    assert loaded[1].interval_seconds == 30
    assert loaded[1].next_run_at == now
    assert loaded[1].last_run_at == now + timedelta(seconds=5)
    assert loaded[1].last_status == "success"
    assert loaded[1].retry_count == 1
    assert loaded[1].max_retries == 3
    assert loaded[1].retry_delay_seconds == 10
    assert loaded[1].payload == {"x": 1}


def test_task_store_load_missing_file_returns_empty_list(tmp_path):
    task_file = tmp_path / "missing_tasks.json"
    store = TaskStore(task_file)

    loaded = store.load()

    assert loaded == []