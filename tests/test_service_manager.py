from __future__ import annotations

from agentic_hub.core.service_manager import ServiceManager


class DummyService:
    def __init__(self) -> None:
        self.running = False
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.running = True
        self.starts += 1

    def stop(self) -> None:
        self.running = False
        self.stops += 1

    def is_running(self) -> bool:
        return self.running

    def status(self) -> dict:
        return {"running": self.running}


class FailingStartService(DummyService):
    def start(self) -> None:
        raise RuntimeError("boom")


class FailingStopService(DummyService):
    def stop(self) -> None:
        raise RuntimeError("stop boom")


def test_register_and_status_default_stopped() -> None:
    manager = ServiceManager()
    svc = DummyService()

    manager.register("telegram", svc, metadata={"transport": "telegram"})
    status = manager.status("telegram")

    assert status["name"] == "telegram"
    assert status["state"] == "stopped"
    assert status["metadata"] == {"transport": "telegram"}
    assert status["service_status"] == {"running": False}


def test_start_service_sets_running() -> None:
    manager = ServiceManager()
    svc = DummyService()
    manager.register("telegram", svc)

    result = manager.start("telegram")
    status = manager.status("telegram")

    assert result["ok"] is True
    assert "started" in result["message"]
    assert status["state"] == "running"
    assert status["started_at"] is not None
    assert svc.starts == 1


def test_start_service_twice_is_idempotent() -> None:
    manager = ServiceManager()
    svc = DummyService()
    manager.register("telegram", svc)

    manager.start("telegram")
    result = manager.start("telegram")

    assert result["ok"] is True
    assert "already running" in result["message"]
    assert svc.starts == 1


def test_stop_service_sets_stopped() -> None:
    manager = ServiceManager()
    svc = DummyService()
    manager.register("telegram", svc)

    manager.start("telegram")
    result = manager.stop("telegram")
    status = manager.status("telegram")

    assert result["ok"] is True
    assert "stopped" in result["message"]
    assert status["state"] == "stopped"
    assert status["stopped_at"] is not None
    assert svc.stops == 1


def test_stop_service_twice_is_idempotent() -> None:
    manager = ServiceManager()
    svc = DummyService()
    manager.register("telegram", svc)

    result = manager.stop("telegram")

    assert result["ok"] is True
    assert "already stopped" in result["message"]
    assert svc.stops == 0


def test_start_failure_sets_failed_state() -> None:
    manager = ServiceManager()
    svc = FailingStartService()
    manager.register("telegram", svc)

    result = manager.start("telegram")
    status = manager.status("telegram")

    assert result["ok"] is False
    assert result["error"] == "boom"
    assert status["state"] == "failed"
    assert status["last_error"] == "boom"


def test_stop_failure_sets_failed_state() -> None:
    manager = ServiceManager()
    svc = FailingStopService()
    svc.running = True
    manager.register("telegram", svc)

    result = manager.stop("telegram")
    status = manager.status("telegram")

    assert result["ok"] is False
    assert result["error"] == "stop boom"
    assert status["state"] == "failed"
    assert status["last_error"] == "stop boom"


def test_list_status_returns_all_services() -> None:
    manager = ServiceManager()
    manager.register("one", DummyService())
    manager.register("two", DummyService())

    rows = manager.list_status()
    names = {row["name"] for row in rows}

    assert names == {"one", "two"}

