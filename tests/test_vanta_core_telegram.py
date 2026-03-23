from __future__ import annotations

from pathlib import Path

from storage.sqlite.db import SQLiteStore
from vanta_core.interview import AgentInterviewService
from vanta_core.service import VantaCoreService
from vanta_core.telegram_bot import VantaCoreTelegramBot


class StubOutput:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.commands: list[list[dict]] = []

    def send(self, payload: dict) -> dict:
        self.sent.append(payload)
        return {"status": "sent"}

    def set_my_commands(self, commands: list[dict[str, str]]) -> dict:
        self.commands.append(commands)
        return {"status": "sent"}


def test_vanta_core_telegram_registers_v1_commands(tmp_path: Path):
    service = VantaCoreService(tmp_path)
    interview = AgentInterviewService(SQLiteStore(tmp_path / "data" / "hub.db"), service.specs)
    output = StubOutput()
    bot = VantaCoreTelegramBot(service=service, interview=interview, output=output, bot_token="token", offset_path=tmp_path / "offset.txt")

    bot._register_commands()

    names = {item["command"] for item in output.commands[0]}
    assert "runtime_status" in names
    assert "activate_agent" in names
    assert "new_agent" in names


def test_vanta_core_telegram_runs_short_agent_interview(tmp_path: Path):
    service = VantaCoreService(tmp_path)
    interview = AgentInterviewService(SQLiteStore(tmp_path / "data" / "hub.db"), service.specs)
    output = StubOutput()
    bot = VantaCoreTelegramBot(service=service, interview=interview, output=output, bot_token="token", offset_path=tmp_path / "offset.txt")

    updates = [
        {"update_id": 1, "message": {"message_id": 1, "from": {"id": 7}, "chat": {"id": 123}, "text": "/new_agent"}},
        {"update_id": 2, "message": {"message_id": 2, "from": {"id": 7}, "chat": {"id": 123}, "text": "fresh_worker"}},
        {"update_id": 3, "message": {"message_id": 3, "from": {"id": 7}, "chat": {"id": 123}, "text": "Handle one simple execution path."}},
        {"update_id": 4, "message": {"message_id": 4, "from": {"id": 7}, "chat": {"id": 123}, "text": "executor"}},
        {"update_id": 5, "message": {"message_id": 5, "from": {"id": 7}, "chat": {"id": 123}, "text": "internal"}},
        {"update_id": 6, "message": {"message_id": 6, "from": {"id": 7}, "chat": {"id": 123}, "text": "bounded"}},
        {"update_id": 7, "message": {"message_id": 7, "from": {"id": 7}, "chat": {"id": 123}, "text": "cheap"}},
        {"update_id": 8, "message": {"message_id": 8, "from": {"id": 7}, "chat": {"id": 123}, "text": "minimal"}},
    ]

    for update in updates:
        bot._handle_update(update)

    assert service.specs.get_spec("fresh_worker") is not None
    assert "Created draft spec: fresh_worker" in output.sent[-1]["text"]


def test_vanta_core_telegram_plain_text_gets_help(tmp_path: Path):
    service = VantaCoreService(tmp_path)
    interview = AgentInterviewService(SQLiteStore(tmp_path / "data" / "hub.db"), service.specs)
    output = StubOutput()
    bot = VantaCoreTelegramBot(service=service, interview=interview, output=output, bot_token="token", offset_path=tmp_path / "offset.txt")

    bot._handle_update(
        {"update_id": 1, "message": {"message_id": 1, "from": {"id": 7}, "chat": {"id": 123}, "text": "hello"}}
    )

    assert "ops mode" in output.sent[-1]["text"]
