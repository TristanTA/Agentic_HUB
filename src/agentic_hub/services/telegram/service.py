from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from agentic_hub.core.task_types import HubTask
from agentic_hub.services.telegram.client import TelegramClient


class TelegramPollingService:
    BOT_COMMANDS = [
        {"command": "help", "description": "Show command guide"},
        {"command": "status", "description": "Show hub status"},
        {"command": "workers", "description": "List workers"},
        {"command": "tasks", "description": "List tasks"},
        {"command": "inspect", "description": "Inspect an object"},
        {"command": "new", "description": "Create a new object"},
        {"command": "edit", "description": "Edit an object"},
        {"command": "delete", "description": "Delete or disable an object"},
        {"command": "logs", "description": "Show recent logs"},
        {"command": "tools", "description": "List tools"},
        {"command": "loadouts", "description": "List loadouts"},
        {"command": "roles", "description": "List roles"},
        {"command": "types", "description": "List worker types"},
        {"command": "pause", "description": "Pause a worker or the hub"},
        {"command": "resume", "description": "Resume a worker or the hub"},
        {"command": "retry", "description": "Retry failed work"},
        {"command": "telegram", "description": "Manage worker Telegram bots"},
        {"command": "chat_open", "description": "Open a hybrid worker chat session"},
        {"command": "chat", "description": "Send a message to a hybrid worker"},
        {"command": "chat_close", "description": "Close hybrid worker chat sessions"},
    ]

    def __init__(
        self,
        hub: Any,
        bot_token: str,
        allowed_user_ids: set[int] | None = None,
        poll_timeout: int = 20,
        idle_sleep: float = 1.0,
        mode: str = "control",
        worker_id: str | None = None,
        bot_username: str | None = None,
    ) -> None:
        self.hub = hub
        self.client = TelegramClient(bot_token)
        self.allowed_user_ids = allowed_user_ids or set()
        self.poll_timeout = poll_timeout
        self.idle_sleep = idle_sleep
        self.mode = mode
        self.worker_id = worker_id
        self.bot_username = bot_username.lower() if bot_username else None

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._offset: int | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if self._running:
            return
        self.client.set_my_commands(self.BOT_COMMANDS)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="telegram-polling", daemon=True)
        self._thread.start()
        self._running = True

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._running = False

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        return {
            "running": self.is_running(),
            "offset": self._offset,
            "last_error": self._last_error,
            "allowed_user_ids": sorted(self.allowed_user_ids),
            "mode": self.mode,
            "worker_id": self.worker_id,
            "bot_username": self.bot_username,
        }

    def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                data = self.client.get_updates(offset=self._offset, timeout=self.poll_timeout)
                if not data.get("ok", False):
                    time.sleep(self.idle_sleep)
                    continue

                for update in data.get("result", []):
                    self._offset = update["update_id"] + 1
                    self._handle_update(update)

                time.sleep(0.1)

        except Exception as exc:
            self._last_error = str(exc)
            self._running = False
            raise
        finally:
            self._running = False

    def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not message:
            return

        from_user = message.get("from", {})
        user_id = from_user.get("id")
        is_bot = bool(from_user.get("is_bot"))
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        text = (message.get("text") or "").strip()

        if not text or chat_id is None or user_id is None:
            return

        if is_bot:
            return

        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            self.client.send_message(chat_id, "unauthorized")
            return

        if self.mode == "managed":
            routed = self._route_managed_message(text=text, chat_type=chat_type, chat_id=chat_id, user_id=user_id)
            if routed is None:
                return
            self.client.send_message(chat_id, routed)
            return

        task = HubTask(
            task_id=str(uuid.uuid4()),
            kind="telegram.command",
            payload={
                "command": text,
                "source": "telegram",
                "chat_id": chat_id,
                "user_id": user_id,
                "message_id": message.get("message_id"),
            },
        )

        try:
            result = self.hub.submit_and_run_task(task)
            response_text = "ok"
            if isinstance(result, dict):
                response_text = str(result.get("text", result))
            elif isinstance(result, str):
                response_text = result
        except Exception as exc:
            self._last_error = str(exc)
            response_text = f"error: {exc}"

        self.client.send_message(chat_id, response_text)

    def _route_managed_message(self, *, text: str, chat_type: str, chat_id: int, user_id: int) -> str | None:
        if self.worker_id is None:
            return "managed worker is not configured"

        routed_text = text
        if chat_type in {"group", "supergroup"}:
            if not self.bot_username:
                return None
            mention = f"@{self.bot_username}"
            lowered = text.lower()
            if mention not in lowered:
                return None
            start = lowered.index(mention)
            end = start + len(mention)
            routed_text = (text[:start] + text[end:]).strip()
            if not routed_text:
                return None
        elif text in {"/start", "/help"}:
            return f"{self.worker_id} is online. Message normally here, or mention this bot in groups."

        return self.hub.handle_managed_message(
            worker_id=self.worker_id,
            text=routed_text,
            payload={"source": "telegram_managed", "chat_id": chat_id, "user_id": user_id, "chat_type": chat_type},
        )


