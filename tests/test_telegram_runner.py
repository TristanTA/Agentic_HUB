from __future__ import annotations

import json
from pathlib import Path

from hub.telegram_runner import TelegramBotRunner


class StubTelegramOutput:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.actions: list[tuple[str, str]] = []
        self.callback_answers: list[str] = []
        self.commands_registered: list[list[dict[str, str]]] = []

    def send(self, payload: dict) -> dict:
        self.sent.append(payload)
        return {"status": "sent"}

    def send_chat_action(self, thread_id: str, action: str = "typing") -> dict:
        self.actions.append((thread_id, action))
        return {"status": "sent"}

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> dict:
        self.callback_answers.append(callback_query_id)
        return {"status": "sent"}

    def set_my_commands(self, commands: list[dict[str, str]]) -> dict:
        self.commands_registered.append(commands)
        return {"status": "sent"}


class StubRuntime:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.bundle = type(
            "Bundle",
            (),
            {"hub_config": type("HubCfg", (), {"telegram": type("TelegramCfg", (), {"allowed_chat_ids": []})(), "hub": type("HubInner", (), {"sqlite_path": "data/hub.db"})()})()},
        )()
        self.telegram_output = StubTelegramOutput()
        self.reloaded = False
        self.processed: list[str] = []

    def process_event(self, event):
        self.processed.append(event.text)
        return {"run_id": "1", "output_text": "ok"}

    def reload_config(self) -> None:
        self.reloaded = True


class StubControlPlane:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.commands: list[str] = []
        self.builder = object()

    def handle_management_command(self, text: str) -> dict:
        self.commands.append(text)
        return self.response

    def format_management_result(self, result: dict) -> str:
        return json.dumps(result, sort_keys=True)


class StubWizardResponse:
    def __init__(self, text: str, reply_markup: dict | None = None, final_result: dict | None = None) -> None:
        self.text = text
        self.reply_markup = reply_markup
        self.final_result = final_result


class StubWizard:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.text_inputs: list[tuple[str, str]] = []
        self.callback_inputs: list[tuple[str, str]] = []
        self.next_text_response: StubWizardResponse | None = None
        self.next_callback_response: StubWizardResponse | None = None

    def start_new_agent(self, session_key: str) -> StubWizardResponse:
        self.started.append(session_key)
        return StubWizardResponse("start wizard", {"inline_keyboard": [[{"text": "Cancel", "callback_data": "cancel"}]]})

    def handle_text(self, session_key: str, text: str) -> StubWizardResponse | None:
        self.text_inputs.append((session_key, text))
        return self.next_text_response

    def handle_callback(self, session_key: str, callback_data: str) -> StubWizardResponse | None:
        self.callback_inputs.append((session_key, callback_data))
        return self.next_callback_response


def make_runner(tmp_path: Path, control_response: dict | None = None):
    runtime = StubRuntime(tmp_path)
    control = StubControlPlane(control_response or {"status": "ok"})
    wizard = StubWizard()
    runner = TelegramBotRunner(
        runtime=runtime,
        control_plane=control,
        wizard=wizard,
        bot_token="token",
        allowed_chat_ids=set(),
        offset_path=tmp_path / "offset.txt",
    )
    return runner, runtime, control, wizard


def test_telegram_runner_routes_commands_to_control_plane(tmp_path: Path):
    runner, runtime, control, wizard = make_runner(tmp_path, {"status": "reloaded"})

    runner._handle_update(
        {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {"id": 456},
                "chat": {"id": 123},
                "text": "/reload",
            },
        }
    )

    assert control.commands == ["/reload"]
    assert runtime.reloaded is True
    assert runtime.telegram_output.sent[0]["thread_id"] == "123"
    assert wizard.started == []


def test_telegram_runner_starts_new_agent_wizard(tmp_path: Path):
    runner, runtime, control, wizard = make_runner(tmp_path)

    runner._handle_update(
        {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {"id": 456},
                "chat": {"id": 123},
                "text": "/new_agent",
            },
        }
    )

    assert wizard.started == ["123:456"]
    assert runtime.telegram_output.sent[0]["text"] == "start wizard"
    assert control.commands == []


def test_telegram_runner_routes_plain_messages_to_runtime_with_typing(tmp_path: Path):
    runner, runtime, control, wizard = make_runner(tmp_path)

    runner._handle_update(
        {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {"id": 456},
                "chat": {"id": 123},
                "text": "hello vanta",
            },
        }
    )

    assert runtime.processed == ["hello vanta"]
    assert runtime.telegram_output.actions == [("123", "typing")]
    assert control.commands == []


def test_telegram_runner_handles_wizard_callback_and_reloads_if_needed(tmp_path: Path):
    runner, runtime, control, wizard = make_runner(tmp_path)
    wizard.next_callback_response = StubWizardResponse("created", final_result={"status": "created"})

    runner._handle_update(
        {
            "update_id": 1,
            "callback_query": {
                "id": "cbq1",
                "from": {"id": 456},
                "data": "wizard:new_agent:skills:general_style",
                "message": {
                    "message_id": 10,
                    "chat": {"id": 123},
                },
            },
        }
    )

    assert wizard.callback_inputs == [("123:456", "wizard:new_agent:skills:general_style")]
    assert runtime.telegram_output.callback_answers == ["cbq1"]
    assert runtime.reloaded is True
    assert runtime.telegram_output.sent[0]["text"] == "created"
