from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import error, parse, request

from shared.telegram_input import normalize_telegram_payload
from shared.telegram_output import TelegramOutputAdapter
from storage.sqlite.db import SQLiteStore
from vanta_core.interview import AgentInterviewService
from vanta_core.service import VantaCoreService


@dataclass(slots=True)
class VantaCoreTelegramBot:
    service: VantaCoreService
    interview: AgentInterviewService
    output: TelegramOutputAdapter
    bot_token: str
    offset_path: Path

    def run_forever(self, poll_timeout: int = 30, sleep_seconds: float = 1.0) -> None:
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self._register_commands()
        while True:
            try:
                offset = self._load_offset()
                updates = self._get_updates(offset=offset, timeout=poll_timeout)
                self.service.resolve_incidents(
                    component="vanta_core",
                    failure_type="RuntimeError",
                    last_action="run_forever",
                    resolution_note="Telegram polling recovered.",
                )
                for update in updates:
                    update_id = int(update.get("update_id", 0))
                    self._store_offset(update_id + 1)
                    self._handle_update(update)
                if not updates:
                    time.sleep(sleep_seconds)
            except Exception as exc:
                self.service.record_incident(
                    component="vanta_core",
                    summary=f"Telegram polling failure: {type(exc).__name__}",
                    likely_cause=str(exc),
                    failure_type=type(exc).__name__,
                    last_action="run_forever",
                )
                time.sleep(sleep_seconds)

    def _handle_update(self, update: dict) -> None:
        event = normalize_telegram_payload(update)
        thread_id = str(event.thread_id)
        session_key = f"{thread_id}:{update.get('message', {}).get('from', {}).get('id', '')}"
        if event.text.startswith("/new_agent"):
            self.output.send({"thread_id": thread_id, "text": self.interview.start(session_key)})
            return
        interview_reply = self.interview.handle_text(session_key, event.text)
        if interview_reply is not None and not event.text.startswith("/"):
            self.output.send({"thread_id": thread_id, "text": interview_reply})
            return
        result = self.service.handle_command(event.text)
        self.output.send({"thread_id": thread_id, "text": self.service.format_result(result)})

    def _get_updates(self, *, offset: int, timeout: int) -> list[dict]:
        query = parse.urlencode({"offset": offset, "timeout": timeout})
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?{query}"
        req = request.Request(url, method="GET")
        try:
            with request.urlopen(req, timeout=timeout + 10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram getUpdates failed ({exc.code}): {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Telegram network error: {exc.reason}") from exc
        if not payload.get("ok", False):
            raise RuntimeError(f"Telegram API returned not ok: {payload}")
        return payload.get("result", [])

    def _register_commands(self) -> None:
        self.output.set_my_commands(
            [
                {"command": "status", "description": "Show Vanta supervisor status"},
                {"command": "runtime_status", "description": "Show Agent OS runtime status"},
                {"command": "provider_status", "description": "Show provider readiness"},
                {"command": "incident", "description": "Show the latest incident"},
                {"command": "agents", "description": "List tracked agents"},
                {"command": "agent", "description": "Inspect one agent"},
                {"command": "explain_agent", "description": "Explain agent visibility"},
                {"command": "restart_runtime", "description": "Restart the Agent OS runtime"},
                {"command": "validate_agent", "description": "Validate one agent spec"},
                {"command": "activate_agent", "description": "Activate one agent"},
                {"command": "deactivate_agent", "description": "Deactivate one agent"},
                {"command": "new_agent", "description": "Start a short agent interview"},
            ]
        )

    def _load_offset(self) -> int:
        if not self.offset_path.exists():
            return 0
        try:
            return int(self.offset_path.read_text(encoding="utf-8").strip())
        except ValueError:
            return 0

    def _store_offset(self, offset: int) -> None:
        self.offset_path.write_text(str(offset), encoding="utf-8")


def build_bot(root_dir: Path) -> VantaCoreTelegramBot:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    service = VantaCoreService(root_dir)
    store = SQLiteStore(root_dir / "data" / "hub.db")
    interview = AgentInterviewService(store, service.specs)
    output = TelegramOutputAdapter(enabled=True)
    return VantaCoreTelegramBot(
        service=service,
        interview=interview,
        output=output,
        bot_token=token,
        offset_path=root_dir / "data" / "vanta_core_telegram_offset.txt",
    )
