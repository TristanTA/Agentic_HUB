from __future__ import annotations

import threading

from hub.integrations.telegram_service import TelegramPollingService


class FakeClient:
    def __init__(self, updates=None, fail_on_get: Exception | None = None) -> None:
        self.updates = updates or []
        self.fail_on_get = fail_on_get
        self.sent_messages: list[tuple[int, str]] = []
        self.commands_set: list[dict[str, str]] | None = None
        self.calls = 0

    def get_updates(self, offset=None, timeout=20) -> dict:
        self.calls += 1
        if self.fail_on_get:
            raise self.fail_on_get
        if self.calls == 1:
            return {"ok": True, "result": self.updates}
        return {"ok": True, "result": []}

    def send_message(self, chat_id: int, text: str) -> dict:
        self.sent_messages.append((chat_id, text))
        return {"ok": True}

    def set_my_commands(self, commands: list[dict[str, str]]) -> dict:
        self.commands_set = commands
        return {"ok": True}


class FakeHub:
    def __init__(self) -> None:
        self.received_tasks = []

    def submit_and_run_task(self, task):
        self.received_tasks.append(task)
        command = task.payload["command"]
        if command == "/ping":
            return {"text": "hub alive"}
        return {"text": f"echo: {command}"}


def make_service(hub: FakeHub, client: FakeClient, allowed_user_ids=None) -> TelegramPollingService:
    service = TelegramPollingService(
        hub=hub,
        bot_token="fake-token",
        allowed_user_ids=allowed_user_ids or set(),
        poll_timeout=0,
        idle_sleep=0,
    )
    service.client = client
    return service


def test_handle_update_authorized_user_creates_task_and_sends_response() -> None:
    hub = FakeHub()
    client = FakeClient()
    service = make_service(hub, client, allowed_user_ids={123})

    update = {
        "update_id": 100,
        "message": {
            "message_id": 10,
            "text": "/ping",
            "chat": {"id": 999},
            "from": {"id": 123},
        },
    }

    service._handle_update(update)

    assert len(hub.received_tasks) == 1
    task = hub.received_tasks[0]
    assert task.kind == "telegram.command"
    assert task.payload["command"] == "/ping"
    assert task.payload["chat_id"] == 999
    assert task.payload["user_id"] == 123
    assert client.sent_messages == [(999, "hub alive")]


def test_handle_update_unauthorized_user_is_rejected() -> None:
    hub = FakeHub()
    client = FakeClient()
    service = make_service(hub, client, allowed_user_ids={123})

    update = {
        "update_id": 100,
        "message": {
            "message_id": 10,
            "text": "/ping",
            "chat": {"id": 999},
            "from": {"id": 555},
        },
    }

    service._handle_update(update)

    assert hub.received_tasks == []
    assert client.sent_messages == [(999, "unauthorized")]


def test_handle_update_ignores_missing_text() -> None:
    hub = FakeHub()
    client = FakeClient()
    service = make_service(hub, client)

    update = {
        "update_id": 100,
        "message": {
            "message_id": 10,
            "chat": {"id": 999},
            "from": {"id": 123},
        },
    }

    service._handle_update(update)

    assert hub.received_tasks == []
    assert client.sent_messages == []


def test_run_loop_advances_offset_and_processes_update() -> None:
    hub = FakeHub()
    updates = [
        {
            "update_id": 200,
            "message": {
                "message_id": 11,
                "text": "/ping",
                "chat": {"id": 999},
                "from": {"id": 123},
            },
        }
    ]
    client = FakeClient(updates=updates)
    service = make_service(hub, client, allowed_user_ids={123})

    def stop_after_first_message(chat_id: int, text: str) -> dict:
        client.sent_messages.append((chat_id, text))
        service._stop_event.set()
        return {"ok": True}

    client.send_message = stop_after_first_message  # type: ignore[method-assign]

    service._run_loop()

    assert service._offset == 201
    assert len(hub.received_tasks) == 1
    assert client.sent_messages == [(999, "hub alive")]


def test_run_loop_records_last_error_on_failure() -> None:
    hub = FakeHub()
    client = FakeClient(fail_on_get=RuntimeError("poll failed"))
    service = make_service(hub, client)

    try:
        service._run_loop()
    except RuntimeError:
        pass

    assert service._last_error == "poll failed"
    assert service.is_running() is False


def test_start_and_stop_service_lifecycle() -> None:
    hub = FakeHub()
    client = FakeClient()
    service = make_service(hub, client)

    original_run_loop = service._run_loop

    def fast_run_loop() -> None:
        service._running = True
        service._stop_event.wait(timeout=1)
        service._running = False

    service._run_loop = fast_run_loop  # type: ignore[method-assign]

    service.start()
    assert service.is_running() is True
    assert client.commands_set is not None
    assert any(item["command"] == "help" for item in client.commands_set)

    service.stop()
    assert service.is_running() is False

    service._run_loop = original_run_loop  # type: ignore[method-assign]


def test_status_reports_expected_fields() -> None:
    hub = FakeHub()
    client = FakeClient()
    service = make_service(hub, client, allowed_user_ids={123, 456})

    status = service.status()

    assert status["running"] is False
    assert status["offset"] is None
    assert status["last_error"] is None
    assert status["allowed_user_ids"] == [123, 456]
