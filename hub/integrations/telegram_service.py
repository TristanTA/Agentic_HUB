from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from hub.core.task_types import HubTask
from hub.integrations.telegram_client import TelegramClient


class TelegramPollingService:
    def __init__(
        self,
        hub: Any,
        bot_token: str,
        allowed_user_ids: set[int] | None = None,
        poll_timeout: int = 20,
        idle_sleep: float = 1.0,
    ) -> None:
        self.hub = hub
        self.client = TelegramClient(bot_token)
        self.allowed_user_ids = allowed_user_ids or set()
        self.poll_timeout = poll_timeout
        self.idle_sleep = idle_sleep

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._offset: int | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if self._running:
            return
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
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        text = (message.get("text") or "").strip()

        if not text or chat_id is None or user_id is None:
            return

        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            self.client.send_message(chat_id, "unauthorized")
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