from agentic_hub.core.executor import Executor
from agentic_hub.core.legacy_tasks import Task


def test_executor_returns_success_for_valid_handler(caplog):
    def ok_handler(payload):
        return {"ok": True, "payload": payload}

    executor = Executor(
        handlers={"ok_handler": ok_handler},
        logger=__import__("logging").getLogger("test_executor_success"),
    )

    task = Task(
        id="1",
        name="Test OK Task",
        handler_name="ok_handler",
        payload={"x": 1},
    )

    result = executor.execute(task)

    assert result.task_id == "1"
    assert result.status == "success"
    assert result.output == {"ok": True, "payload": {"x": 1}}
    assert result.error is None


def test_executor_returns_failed_for_crashing_handler(caplog):
    def bad_handler(payload):
        raise ValueError("boom")

    logger = __import__("logging").getLogger("test_executor_failure")

    executor = Executor(
        handlers={"bad_handler": bad_handler},
        logger=logger,
    )

    task = Task(
        id="2",
        name="Test Bad Task",
        handler_name="bad_handler",
    )

    result = executor.execute(task)

    assert result.task_id == "2"
    assert result.status == "failed"
    assert result.output is None
    assert result.error is not None
    assert "ValueError: boom" in result.error


def test_executor_returns_failed_for_missing_handler():
    logger = __import__("logging").getLogger("test_executor_missing")

    executor = Executor(
        handlers={},
        logger=logger,
    )

    task = Task(
        id="3",
        name="Missing Handler Task",
        handler_name="does_not_exist",
    )

    result = executor.execute(task)

    assert result.task_id == "3"
    assert result.status == "failed"
    assert result.output is None
    assert result.error is not None
    assert "does_not_exist" in result.error

