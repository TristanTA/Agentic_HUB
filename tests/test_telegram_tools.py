from __future__ import annotations

from hub.tools.telegram_tools import (
    start_telegram_service,
    stop_telegram_service,
    telegram_service_status,
)


class DummyService:
    def __init__(self) -> None:
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def is_running(self) -> bool:
        return self.running

    def status(self) -> dict:
        return {"running": self.running}


class DummyServiceManager:
    def __init__(self) -> None:
        self.service = DummyService()

    def start(self, name: str) -> dict:
        assert name == "telegram"
        self.service.start()
        return {"ok": True, "message": "telegram started"}

    def stop(self, name: str) -> dict:
        assert name == "telegram"
        self.service.stop()
        return {"ok": True, "message": "telegram stopped"}

    def status(self, name: str) -> dict:
        assert name == "telegram"
        return {"name": "telegram", "state": "running" if self.service.running else "stopped"}


class DummyHub:
    def __init__(self) -> None:
        self.service_manager = DummyServiceManager()


def test_start_telegram_service_tool() -> None:
    hub = DummyHub()

    result = start_telegram_service(hub)

    assert result["ok"] is True
    assert hub.service_manager.service.running is True


def test_stop_telegram_service_tool() -> None:
    hub = DummyHub()
    hub.service_manager.service.running = True

    result = stop_telegram_service(hub)

    assert result["ok"] is True
    assert hub.service_manager.service.running is False


def test_telegram_service_status_tool() -> None:
    hub = DummyHub()

    result = telegram_service_status(hub)

    assert result["name"] == "telegram"
    assert result["state"] == "stopped"