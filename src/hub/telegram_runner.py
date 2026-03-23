from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib import error, parse, request

from control_plane.service import ControlPlaneService
from control_plane.wizard import TelegramWizardService
from hub.inputs.normalize import normalize_telegram_payload
from hub.outputs.telegram import TelegramOutputAdapter
from hub.runtime.service import HubRuntime
from storage.sqlite.db import SQLiteStore


@dataclass(slots=True)
class TelegramBotRunner:
    runtime: HubRuntime
    control_plane: ControlPlaneService
    wizard: TelegramWizardService
    output: TelegramOutputAdapter
    bot_token: str
    allowed_chat_ids: set[str]
    offset_path: Path
    target_agent_id: str | None = None

    def run_forever(self, poll_timeout: int = 30, sleep_seconds: float = 1.0) -> None:
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)
        self._register_commands()
        while True:
            try:
                offset = self._load_offset()
                updates = self._get_updates(offset=offset, timeout=poll_timeout)
                for update in updates:
                    update_id = int(update.get("update_id", 0))
                    self._store_offset(update_id + 1)
                    self._handle_update(update)
                if not updates:
                    time.sleep(sleep_seconds)
            except Exception as exc:
                self.control_plane.record_incident(
                    component="telegram_runner",
                    summary=f"{type(exc).__name__} in Telegram polling loop",
                    likely_cause=str(exc),
                    failure_type=type(exc).__name__,
                    affected_agent=self.target_agent_id or "vanta_manager",
                    last_action="run_forever",
                    details={"target_agent_id": self.target_agent_id or ""},
                )
                self._log_error(f"telegram_runner_error[{self.target_agent_id or 'vanta'}]: {type(exc).__name__}: {exc}")
                time.sleep(sleep_seconds)

    def _handle_update(self, update: dict) -> None:
        callback_query = update.get("callback_query")
        if callback_query:
            self._handle_callback_query(callback_query)
            return

        event = normalize_telegram_payload(update)
        event.metadata["bot_token_env"] = self.output.bot_token_env
        thread_id = str(event.thread_id)
        if self.allowed_chat_ids and thread_id not in self.allowed_chat_ids:
            return

        try:
            if self.target_agent_id:
                self.output.send_chat_action(thread_id, "typing")
                result = self.runtime.process_event_for_agent(event, self.target_agent_id, output_adapter=self.output)
                if result.get("status") == "paused":
                    self._safe_send(thread_id=thread_id, text="Hub is paused.", last_action="direct_paused_notice")
                return

            session_key = self._session_key(chat_id=thread_id, user_id=str(update.get("message", {}).get("from", {}).get("id", "")))
            wizard_reply = self.wizard.handle_text(session_key, event.text)
            if wizard_reply is not None:
                self._safe_send(
                    thread_id=thread_id,
                    text=wizard_reply.text,
                    reply_markup=wizard_reply.reply_markup,
                    last_action="wizard_reply",
                )
                return

            if event.text.startswith("/"):
                if event.text.split()[0].startswith("/new_agent"):
                    wizard_result = self.wizard.start_new_agent(session_key)
                    self._safe_send(
                        thread_id=thread_id,
                        text=wizard_result.text,
                        reply_markup=wizard_result.reply_markup,
                        last_action="wizard_start",
                    )
                    return
                result = self.control_plane.handle_management_command(event.text)
                if result.get("status") in {"created", "reloaded", "updated"}:
                    self.runtime.reload_config()
                text = self.control_plane.format_management_result(result)
                self._safe_send(thread_id=thread_id, text=text, last_action="management_command")
                return

            self.output.send_chat_action(thread_id, "typing")
            result = self.runtime.process_event(event)
            if result.get("status") == "paused":
                self._safe_send(thread_id=thread_id, text="Hub is paused.", last_action="paused_notice")
        except Exception as exc:
            incident = self.control_plane.record_incident(
                component="telegram_runner",
                summary=f"{type(exc).__name__} while handling Telegram update",
                likely_cause=str(exc),
                failure_type=type(exc).__name__,
                affected_agent=self.target_agent_id or "vanta_manager",
                last_action="handle_update",
                thread_id=thread_id,
                details={"target_agent_id": self.target_agent_id or ""},
            )
            self._log_error(f"telegram_runner_error[{self.target_agent_id or 'vanta'}]: {type(exc).__name__}: {exc}")
            self._safe_send(
                thread_id=thread_id,
                text=self.control_plane.format_incident_report(incident),
                last_action="incident_report",
            )

    def _handle_callback_query(self, callback_query: dict) -> None:
        if self.target_agent_id:
            self.output.answer_callback_query(callback_query.get("id", ""))
            return
        callback_id = callback_query.get("id", "")
        message = callback_query.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        user_id = str(callback_query.get("from", {}).get("id", ""))
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            return

        session_key = self._session_key(chat_id=chat_id, user_id=user_id)
        result = self.wizard.handle_callback(session_key, callback_query.get("data", ""))
        self.output.answer_callback_query(callback_id)
        if result is None:
            return
        if result.final_result and result.final_result.get("status") in {"created", "reloaded", "updated"}:
            self.runtime.reload_config()
        self._safe_send(thread_id=chat_id, text=result.text, reply_markup=result.reply_markup, last_action="callback_reply")

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

    def _load_offset(self) -> int:
        if not self.offset_path.exists():
            return 0
        raw = self.offset_path.read_text(encoding="utf-8").strip()
        try:
            return int(raw)
        except ValueError:
            return 0

    def _store_offset(self, offset: int) -> None:
        self.offset_path.write_text(str(offset), encoding="utf-8")

    def _log_error(self, message: str) -> None:
        log_path = self.runtime.root_dir / "logs" / "telegram_runner.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")

    def _safe_send(self, *, thread_id: str, text: str, last_action: str, reply_markup: dict | None = None) -> dict:
        result = self.output.send({"thread_id": thread_id, "text": text, "reply_markup": reply_markup})
        if result.get("status") == "sent":
            return result
        self.control_plane.record_incident(
            component="telegram_runner",
            summary="Telegram send returned a non-sent status",
            likely_cause=result.get("reason") or result.get("detail") or "Telegram output adapter could not deliver the message.",
            failure_type="TelegramSendFailure",
            affected_agent=self.target_agent_id or "vanta_manager",
            last_action=last_action,
            thread_id=thread_id,
            severity="medium",
            details=result,
        )
        self._log_error(f"telegram_send_failure[{self.target_agent_id or 'vanta'}]: {result}")
        return result

    def _register_commands(self) -> None:
        if self.target_agent_id:
            self.output.set_my_commands([{"command": "status", "description": f"Talk to {self.target_agent_id}"}])
            return
        commands = [
            {"command": "help", "description": "Show available command groups"},
            {"command": "new_agent", "description": "Create a new agent with a guided wizard"},
            {"command": "agents", "description": "List all registered agents"},
            {"command": "agent", "description": "Inspect one agent"},
            {"command": "workers", "description": "List worker-capable agents"},
            {"command": "tasks", "description": "List active and recent tasks"},
            {"command": "delegate", "description": "Dispatch a task to a worker"},
            {"command": "review_agent", "description": "Review one agent for weaknesses"},
            {"command": "improve_agent", "description": "Apply a bounded improvement to an agent"},
            {"command": "attach_agent", "description": "Attach an external agent profile"},
            {"command": "promote_agent", "description": "Promote an agent to a new exposure mode"},
            {"command": "status", "description": "Show hub and health status"},
            {"command": "health", "description": "Show latest health snapshot"},
            {"command": "reload", "description": "Reload hub configuration"},
            {"command": "errors", "description": "Show recent runtime errors"},
            {"command": "incident", "description": "Show the latest structured incident"},
            {"command": "last_failure", "description": "Show the latest failure summary"},
            {"command": "provider_status", "description": "Show provider readiness"},
            {"command": "trace", "description": "Inspect one run trace"},
            {"command": "logs", "description": "Show recent hub or Telegram logs"},
            {"command": "routes", "description": "Show routing rules"},
            {"command": "vanta_status", "description": "Show Vanta autonomy status"},
            {"command": "vanta_focus", "description": "Show Vanta's current highest-leverage focus"},
            {"command": "vanta_digest", "description": "Show a compact digest of Vanta activity"},
            {"command": "vanta_docs", "description": "Show Vanta's owned documents"},
            {"command": "vanta_lessons", "description": "Show Vanta's recent lessons"},
            {"command": "vanta_changes", "description": "Show Vanta's recent autonomous changes"},
            {"command": "vanta_memory", "description": "Inspect Vanta's stored memory and working state"},
            {"command": "vanta_review", "description": "Show the latest Vanta review"},
            {"command": "vanta_scorecard", "description": "Show Vanta's self-evaluation summary"},
            {"command": "memory_search", "description": "Search Vanta's long-term memory"},
            {"command": "triage", "description": "Suggest the best specialist for a request"},
            {"command": "consolidate_vanta", "description": "Check Vanta prompts/skills for duplicate guidance"},
            {"command": "scorecards", "description": "Show agent effectiveness scorecards"},
            {"command": "rollback_change", "description": "Roll back one tracked Vanta change"},
            {"command": "pause", "description": "Pause the hub"},
            {"command": "resume", "description": "Resume the hub"},
            {"command": "restart", "description": "Restart the hub"},
        ]
        self.output.set_my_commands(commands)

    def _session_key(self, *, chat_id: str, user_id: str) -> str:
        return f"{chat_id}:{user_id}"


def build_runners(runtime: HubRuntime, control_plane: ControlPlaneService) -> list[TelegramBotRunner]:
    runners: list[TelegramBotRunner] = []
    main_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not main_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

    main_output = TelegramOutputAdapter(enabled=runtime.bundle.hub_config.telegram.enabled, bot_token_env="TELEGRAM_BOT_TOKEN")
    allowed_chat_ids = {
        item.strip()
        for item in runtime.bundle.hub_config.telegram.allowed_chat_ids
        if str(item).strip()
    }
    wizard = TelegramWizardService(SQLiteStore(runtime.root_dir / runtime.bundle.hub_config.hub.sqlite_path), control_plane.builder)
    runners.append(
        TelegramBotRunner(
            runtime=runtime,
            control_plane=control_plane,
            wizard=wizard,
            output=main_output,
            bot_token=main_token,
            allowed_chat_ids=allowed_chat_ids,
            offset_path=runtime.root_dir / "data" / "telegram_update_offset.txt",
        )
    )

    for spec in runtime.bundle.agents.values():
        if spec.exposure_mode.value != "standalone_telegram":
            continue
        if spec.id == runtime.bundle.hub_config.hub.default_agent:
            continue
        bot_token_env = str(spec.telegram.get("bot_token_env", "")).strip()
        if not bot_token_env or not os.getenv(bot_token_env, "").strip():
            continue
        if spec.telegram.get("owns_polling", True) is False:
            continue
        output = TelegramOutputAdapter(enabled=True, bot_token_env=bot_token_env)
        chat_ids = {str(item).strip() for item in spec.telegram.get("allowed_chat_ids", []) if str(item).strip()}
        runners.append(
            TelegramBotRunner(
                runtime=runtime,
                control_plane=control_plane,
                wizard=wizard,
                output=output,
                bot_token=os.getenv(bot_token_env, "").strip(),
                allowed_chat_ids=chat_ids,
                offset_path=runtime.root_dir / "data" / f"{spec.id}_telegram_offset.txt",
                target_agent_id=spec.id,
            )
        )
    return runners


def run_all_runners(runners: list[TelegramBotRunner]) -> None:
    threads: list[threading.Thread] = []
    for runner in runners[1:]:
        thread = threading.Thread(target=runner.run_forever, name=f"telegram-{runner.target_agent_id}", daemon=True)
        thread.start()
        threads.append(thread)
    runners[0].run_forever()
