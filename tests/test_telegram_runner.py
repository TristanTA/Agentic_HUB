from __future__ import annotations

import json
from pathlib import Path

from hub.telegram_runner import TelegramBotRunner


class StubTelegramOutput:
    def __init__(self, bot_token_env: str = "TELEGRAM_BOT_TOKEN") -> None:
        self.bot_token_env = bot_token_env
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
            {"hub_config": type("HubCfg", (), {"telegram": type("TelegramCfg", (), {"allowed_chat_ids": []})(), "hub": type("HubInner", (), {"sqlite_path": "data/hub.db", "default_agent": "vanta_manager"})()})()},
        )()
        self.reloaded = False
        self.processed: list[str] = []
        self.direct_processed: list[tuple[str, str]] = []

    def process_event(self, event):
        self.processed.append(event.text)
        return {"run_id": "1", "output_text": "ok"}

    def process_event_for_agent(self, event, agent_id: str, output_adapter=None):
        self.direct_processed.append((agent_id, event.text))
        return {"run_id": "2", "output_text": "ok"}

    def reload_config(self) -> None:
        self.reloaded = True


class StubControlPlane:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.commands: list[str] = []
        self.builder = object()
        self.incidents: list[dict] = []

    def handle_management_command(self, text: str) -> dict:
        self.commands.append(text)
        return self.response

    def format_management_result(self, result: dict) -> str:
        return json.dumps(result, sort_keys=True)

    def record_incident(self, **kwargs) -> dict:
        self.incidents.append(kwargs)
        return {"incident": kwargs, **kwargs}

    def format_incident_report(self, result: dict) -> str:
        return f"INCIDENT: {result.get('summary', '')}"


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


def make_runner(tmp_path: Path, control_response: dict | None = None, target_agent_id: str | None = None):
    runtime = StubRuntime(tmp_path)
    control = StubControlPlane(control_response or {"status": "ok"})
    wizard = StubWizard()
    output = StubTelegramOutput()
    runner = TelegramBotRunner(
        runtime=runtime,
        control_plane=control,
        wizard=wizard,
        output=output,
        bot_token="token",
        allowed_chat_ids=set(),
        offset_path=tmp_path / "offset.txt",
        target_agent_id=target_agent_id,
    )
    return runner, runtime, control, wizard, output


def test_telegram_runner_routes_commands_to_control_plane(tmp_path: Path):
    runner, runtime, control, wizard, output = make_runner(tmp_path, {"status": "reloaded"})

    runner._handle_update(
        {"update_id": 1, "message": {"message_id": 10, "from": {"id": 456}, "chat": {"id": 123}, "text": "/reload"}}
    )

    assert control.commands == ["/reload"]
    assert runtime.reloaded is True
    assert output.sent[0]["thread_id"] == "123"
    assert wizard.started == []


def test_telegram_runner_starts_new_agent_wizard(tmp_path: Path):
    runner, runtime, control, wizard, output = make_runner(tmp_path)

    runner._handle_update(
        {"update_id": 1, "message": {"message_id": 10, "from": {"id": 456}, "chat": {"id": 123}, "text": "/new_agent"}}
    )

    assert wizard.started == ["123:456"]
    assert output.sent[0]["text"] == "start wizard"
    assert control.commands == []


def test_telegram_runner_routes_plain_messages_to_runtime_with_typing(tmp_path: Path):
    runner, runtime, control, wizard, output = make_runner(tmp_path)

    runner._handle_update(
        {"update_id": 1, "message": {"message_id": 10, "from": {"id": 456}, "chat": {"id": 123}, "text": "hello vanta"}}
    )

    assert runtime.processed == ["hello vanta"]
    assert output.actions == [("123", "typing")]
    assert control.commands == []


def test_telegram_runner_handles_wizard_callback_and_reloads_if_needed(tmp_path: Path):
    runner, runtime, control, wizard, output = make_runner(tmp_path)
    wizard.next_callback_response = StubWizardResponse("created", final_result={"status": "created"})

    runner._handle_update(
        {
            "update_id": 1,
            "callback_query": {"id": "cbq1", "from": {"id": 456}, "data": "wizard:new_agent:skills:general_style", "message": {"message_id": 10, "chat": {"id": 123}}},
        }
    )

    assert wizard.callback_inputs == [("123:456", "wizard:new_agent:skills:general_style")]
    assert output.callback_answers == ["cbq1"]
    assert runtime.reloaded is True
    assert output.sent[0]["text"] == "created"


def test_direct_agent_runner_bypasses_manager_and_routes_to_target_agent(tmp_path: Path):
    runner, runtime, control, wizard, output = make_runner(tmp_path, target_agent_id="rowan")

    runner._handle_update(
        {"update_id": 1, "message": {"message_id": 10, "from": {"id": 456}, "chat": {"id": 123}, "text": "plan my venue shortlist"}}
    )

    assert runtime.direct_processed == [("rowan", "plan my venue shortlist")]
    assert control.commands == []
    assert wizard.started == []
    assert output.actions == [("123", "typing")]


def test_telegram_runner_registers_vanta_ops_commands(tmp_path: Path):
    runner, runtime, control, wizard, output = make_runner(tmp_path)

    runner._register_commands()

    commands = {item["command"] for item in output.commands_registered[0]}
    assert "vanta_status" in commands
    assert "vanta_docs" in commands
    assert "review_agent" in commands
    assert "vanta_focus" in commands
    assert "rollback_change" in commands
    assert "vanta_digest" in commands
    assert "memory_search" in commands
    assert "incident" in commands
    assert "last_failure" in commands
    assert "provider_status" in commands


def test_telegram_runner_reports_runtime_failure_as_incident(tmp_path: Path):
    runner, runtime, control, wizard, output = make_runner(tmp_path)

    def boom(event):
        raise RuntimeError("runtime exploded")

    runtime.process_event = boom

    runner._handle_update(
        {"update_id": 1, "message": {"message_id": 10, "from": {"id": 456}, "chat": {"id": 123}, "text": "hello vanta"}}
    )

    assert control.incidents
    assert output.sent[-1]["text"].startswith("INCIDENT:")


def test_safe_send_records_non_sent_telegram_result(tmp_path: Path):
    runner, runtime, control, wizard, output = make_runner(tmp_path)

    def fail_send(payload: dict) -> dict:
        output.sent.append(payload)
        return {"status": "error", "reason": "telegram_network_timeout"}

    output.send = fail_send
    runner._safe_send(thread_id="123", text="hello", last_action="test_send")

    assert control.incidents
    assert control.incidents[-1]["failure_type"] == "TelegramSendFailure"
