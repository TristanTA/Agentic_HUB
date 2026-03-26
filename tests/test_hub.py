import json
from datetime import timedelta

import agentic_hub.core.hub as hub_module
from agentic_hub.core.hub import Hub
from agentic_hub.core.legacy_tasks import Task, TaskResult, utc_now


def test_get_next_task_returns_highest_priority_due_task(tmp_path, monkeypatch):
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"
    state_file = tmp_path / "state.json"

    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)

    hub = Hub()
    now = utc_now()

    not_due = Task(
        id="not-due",
        name="Not Due",
        handler_name="interval_task",
        priority=1,
        trigger="interval",
        interval_seconds=30,
        next_run_at=now + timedelta(minutes=10),
    )
    lower_priority = Task(
        id="low-priority-due",
        name="Low Priority Due",
        handler_name="interval_task",
        priority=3,
        trigger="interval",
        interval_seconds=30,
        next_run_at=now,
    )
    higher_priority = Task(
        id="high-priority-due",
        name="High Priority Due",
        handler_name="interval_task",
        priority=1,
        trigger="interval",
        interval_seconds=30,
        next_run_at=now,
    )

    hub.tasks = [not_due, lower_priority, higher_priority]

    task = hub.get_next_task()

    assert task is not None
    assert task.id == "high-priority-due"


def test_handle_result_updates_interval_task_and_reschedules(tmp_path, monkeypatch):
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"
    state_file = tmp_path / "state.json"

    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)

    hub = Hub()

    now = utc_now()
    task = Task(
        id="interval-1",
        name="Interval Task",
        handler_name="interval_task",
        priority=2,
        trigger="interval",
        interval_seconds=30,
        next_run_at=now,
    )
    hub.tasks = [task]

    result = TaskResult(
        task_id=task.id,
        status="success",
        output={"ok": True},
        error=None,
    )

    old_next_run_at = task.next_run_at
    hub.handle_result(task, result)

    assert task.last_status == "success"
    assert task.last_error is None
    assert task.last_run_at is not None
    assert task.next_run_at is not None
    assert task.next_run_at > old_next_run_at
    assert task.retry_count == 0


def test_success_resets_retry_count(tmp_path, monkeypatch):
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"
    state_file = tmp_path / "state.json"

    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)

    hub = Hub()

    task = Task(
        id="interval-success-reset",
        name="Retry Reset Task",
        handler_name="interval_task",
        trigger="interval",
        interval_seconds=30,
        next_run_at=utc_now(),
        retry_count=2,
        max_retries=3,
        retry_delay_seconds=10,
    )
    hub.tasks = [task]

    result = TaskResult(
        task_id=task.id,
        status="success",
        output={"ok": True},
        error=None,
    )

    hub.handle_result(task, result)

    assert task.retry_count == 0
    assert task.last_status == "success"


def test_failure_reschedules_with_exponential_backoff(tmp_path, monkeypatch):
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"
    state_file = tmp_path / "state.json"

    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)

    hub = Hub()

    base_now = utc_now()

    task = Task(
        id="interval-fail-1",
        name="Backoff Task",
        handler_name="interval_task",
        trigger="interval",
        interval_seconds=30,
        next_run_at=base_now,
        retry_count=0,
        max_retries=3,
        retry_delay_seconds=10,
    )
    hub.tasks = [task]

    result = TaskResult(
        task_id=task.id,
        status="failed",
        output=None,
        error="first failure",
    )

    hub.handle_result(task, result)

    assert task.retry_count == 1
    assert task.last_status == "failed"
    assert task.last_error == "first failure"
    assert task.next_run_at is not None

    delay = (task.next_run_at - task.last_run_at).total_seconds()
    assert delay == 10


def test_second_failure_uses_larger_backoff(tmp_path, monkeypatch):
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"
    state_file = tmp_path / "state.json"

    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)

    hub = Hub()

    task = Task(
        id="interval-fail-2",
        name="Second Backoff Task",
        handler_name="interval_task",
        trigger="interval",
        interval_seconds=30,
        next_run_at=utc_now(),
        retry_count=1,
        max_retries=3,
        retry_delay_seconds=10,
    )
    hub.tasks = [task]

    result = TaskResult(
        task_id=task.id,
        status="failed",
        output=None,
        error="second failure",
    )

    hub.handle_result(task, result)

    assert task.retry_count == 2
    delay = (task.next_run_at - task.last_run_at).total_seconds()
    assert delay == 20


def test_task_moves_to_dead_bin_after_max_retries(tmp_path, monkeypatch):
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"
    state_file = tmp_path / "state.json"

    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)

    hub = Hub()

    task = Task(
        id="interval-dead",
        name="Dead Bin Task",
        handler_name="interval_task",
        trigger="interval",
        interval_seconds=30,
        next_run_at=utc_now(),
        retry_count=3,
        max_retries=3,
        retry_delay_seconds=10,
    )
    hub.tasks = [task]

    result = TaskResult(
        task_id=task.id,
        status="failed",
        output=None,
        error="fatal failure",
    )

    hub.handle_result(task, result)

    assert len(hub.tasks) == 0
    assert dead_file.exists()

    dead_data = json.loads(dead_file.read_text(encoding="utf-8"))
    assert len(dead_data) == 1
    assert dead_data[0]["task_data"]["id"] == "interval-dead"
    assert dead_data[0]["reason"] == "fatal failure"
    assert dead_data[0]["retry_count"] == 4


def test_handle_result_disables_once_task(tmp_path, monkeypatch):
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"
    state_file = tmp_path / "state.json"

    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)

    hub = Hub()

    task = Task(
        id="once-1",
        name="One Time Task",
        handler_name="startup_task",
        trigger="once",
        enabled=True,
        next_run_at=utc_now(),
    )
    hub.tasks = [task]

    result = TaskResult(
        task_id=task.id,
        status="success",
        output={"done": True},
        error=None,
    )

    hub.handle_result(task, result)

    assert task.enabled is False
    assert task.last_status == "success"


def test_startup_task_runs_once_per_boot(tmp_path, monkeypatch):
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"
    state_file = tmp_path / "state.json"

    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)

    hub = Hub()

    task = Task(
        id="startup-1",
        name="Startup Task",
        handler_name="startup_task",
        trigger="startup",
        priority=1,
        enabled=True,
    )
    hub.tasks = [task]

    first = hub.get_next_task()
    assert first is not None
    assert first.id == "startup-1"

    result = TaskResult(
        task_id=task.id,
        status="success",
        output={"ok": True},
        error=None,
    )
    hub.handle_result(task, result)

    second = hub.get_next_task()
    assert second is None


def test_shutdown_writes_stopped_state(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"

    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)
    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)

    hub = Hub()
    hub.state.status = "running"

    hub.shutdown()

    assert state_file.exists()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["status"] == "stopped"


def test_run_executes_due_task_and_stops_cleanly(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"

    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)
    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "HEARTBEAT_SECONDS", 0)

    hub = Hub()

    task = Task(
        id="task-123",
        name="Interval Task",
        handler_name="interval_task",
        priority=1,
        trigger="interval",
        interval_seconds=30,
        next_run_at=utc_now(),
        enabled=True,
    )
    hub.tasks = [task]

    original_handle_result = hub.handle_result

    def stop_after_first_result(task, result):
        original_handle_result(task, result)
        hub.request_stop()

    monkeypatch.setattr(hub, "handle_result", stop_after_first_result)

    hub.run()

    assert hub.state.status == "stopped"
    assert hub.state.stop_requested is True
    assert task.last_status == "success"

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["status"] == "stopped"


def test_failed_task_does_not_crash_hub_loop(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"

    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)
    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "HEARTBEAT_SECONDS", 0)

    hub = Hub()

    task = Task(
        id="task-fail",
        name="Failing Interval Task",
        handler_name="interval_task",
        priority=1,
        trigger="interval",
        interval_seconds=30,
        next_run_at=utc_now(),
        enabled=True,
    )
    hub.tasks = [task]

    def fake_execute(task):
        return TaskResult(
            task_id=task.id,
            status="failed",
            output=None,
            error="simulated task failure",
        )

    monkeypatch.setattr(hub.executor, "execute", fake_execute)

    original_handle_result = hub.handle_result

    def stop_after_first_result(task, result):
        original_handle_result(task, result)
        hub.request_stop()

    monkeypatch.setattr(hub, "handle_result", stop_after_first_result)

    hub.run()

    assert hub.state.status == "stopped"
    assert task.last_status == "failed"
    assert task.last_error == "simulated task failure"


def test_hub_creates_default_tasks_file_when_missing(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"

    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)
    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)

    assert not task_file.exists()

    hub = Hub()

    assert task_file.exists()
    assert len(hub.tasks) >= 1


def test_hub_bootstraps_catalog_and_persists_runtime_workers(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"
    runtime_catalog_dir = tmp_path / "catalog"

    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)
    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setattr(hub_module, "CATALOG_RUNTIME_DIR", runtime_catalog_dir)

    hub = Hub()
    assert any(worker.worker_id == "aria" for worker in hub.worker_registry.list_workers())

    hub.catalog_manager.upsert(
        "workers",
        {
            "worker_id": "persisted_worker",
            "name": "Persisted Worker",
            "type_id": "agent_worker",
            "role_id": "operator",
            "loadout_id": "operator_core",
        },
    )

    restarted = Hub()

    assert any(worker.worker_id == "persisted_worker" for worker in restarted.worker_registry.list_workers())


def test_invalid_telegram_allowed_user_ids_are_ignored(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    task_file = tmp_path / "tasks.json"
    dead_file = tmp_path / "dead_tasks.json"

    monkeypatch.setattr(hub_module, "STATE_FILE", state_file)
    monkeypatch.setattr(hub_module, "TASKS_FILE", task_file)
    monkeypatch.setattr(hub_module, "DEAD_TASKS_FILE", dead_file)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123, abc, 456")

    hub = Hub()

    telegram = hub.service_manager._services["telegram"].service
    assert telegram.allowed_user_ids == {123, 456}


