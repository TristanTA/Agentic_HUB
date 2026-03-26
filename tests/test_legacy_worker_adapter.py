from agentic_hub.core.legacy_worker_adapter import LegacyHandlerAdapter
from agentic_hub.models.task import Task
from agentic_hub.models.worker_instance import WorkerInstance


class DummyLogger:
    def error(self, *args, **kwargs):
        return None


def test_legacy_worker_adapter_runs_handler():
    adapter = LegacyHandlerAdapter(
        handlers={"send_message": lambda payload: {"ok": True}},
        logger=DummyLogger(),
    )
    worker = WorkerInstance(
        worker_id="w1",
        name="Worker",
        type_id="tool_worker",
        role_id="operator",
        loadout_id="l1",
    )
    task = Task(task_id="t1", kind="send_message")

    result = adapter.run(worker, task)
    assert result.status == "done"
    assert result.output_payload["result"]["ok"] is True

