from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from agentic_hub.core.logging import get_logger
from agentic_hub.core.task_types import HubTask
from agentic_hub.services.telegram.client import TelegramClient


class TelegramPollingService:
    BOT_COMMANDS = [
        {"command": "help", "description": "Show command guide"},
        {"command": "status", "description": "Show hub status"},
        {"command": "workers", "description": "List workers"},
        {"command": "tasks", "description": "List tasks"},
        {"command": "inspect", "description": "Inspect an object"},
        {"command": "logs", "description": "Show recent logs"},
    ]

    def __init__(
        self,
        hub: Any,
        bot_token: str,
        allowed_user_ids: set[int] | None = None,
        allowed_chat_ids: set[int] | None = None,
        poll_timeout: int = 20,
        idle_sleep: float = 1.0,
        mode: str = "control",
        worker_id: str | None = None,
        bot_username: str | None = None,
    ) -> None:
        self.hub = hub
        self.client = TelegramClient(bot_token)
        self.allowed_user_ids = allowed_user_ids or set()
        self.allowed_chat_ids = allowed_chat_ids or set()
        self.poll_timeout = poll_timeout
        self.idle_sleep = idle_sleep
        self.mode = mode
        self.worker_id = worker_id
        self.bot_username = bot_username.lower() if bot_username else None
        self.logger = get_logger()

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._running = False
        self._offset: int | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if self._running:
            return
        self.client.set_my_commands(self.BOT_COMMANDS)
        self.logger.info(
            "Starting telegram polling service: mode=%s worker=%s bot_username=%s allowed_users=%s",
            self.mode,
            self.worker_id,
            self.bot_username,
            sorted(self.allowed_user_ids),
        )
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
            "allowed_chat_ids": sorted(self.allowed_chat_ids),
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
                    if self.mode == "managed":
                        self.logger.info(
                            "Managed telegram update received: worker=%s update_id=%s keys=%s",
                            self.worker_id,
                            update.get("update_id"),
                            sorted(update.keys()),
                        )
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
            if self.mode == "managed":
                self.logger.info(
                    "Managed telegram update ignored because it had no message payload: worker=%s update_id=%s",
                    self.worker_id,
                    update.get("update_id"),
                )
            return

        from_user = message.get("from", {})
        user_id = from_user.get("id")
        is_bot = bool(from_user.get("is_bot"))
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        message_thread_id = message.get("message_thread_id")
        text = (message.get("text") or "").strip()
        if self.mode == "managed":
            self.logger.info(
                "Managed telegram message observed: worker=%s chat_id=%s user_id=%s chat_type=%s has_text=%s text=%r",
                self.worker_id,
                chat_id,
                user_id,
                chat_type,
                bool(text),
                text,
            )

        if not text or chat_id is None or user_id is None:
            if self.mode == "managed":
                self.logger.info(
                    "Managed telegram update ignored before routing: worker=%s chat_id=%s user_id=%s has_text=%s",
                    self.worker_id,
                    chat_id,
                    user_id,
                    bool(text),
                )
            return

        if is_bot:
            if self.mode == "managed":
                self.logger.info(
                    "Managed telegram update ignored because sender is a bot: worker=%s chat_id=%s user_id=%s",
                    self.worker_id,
                    chat_id,
                    user_id,
                )
            return

        if self.mode == "managed":
            access = self._managed_access(chat_id=chat_id, chat_type=chat_type, user_id=user_id)
            if not access["allowed"]:
                self.logger.info(
                    "Managed telegram update rejected by access rules: worker=%s chat_id=%s user_id=%s chat_type=%s allowed_users=%s allowed_chats=%s",
                    self.worker_id,
                    chat_id,
                    user_id,
                    chat_type,
                    sorted(self.allowed_user_ids),
                    sorted(self.allowed_chat_ids),
                )
                self.client.send_message(chat_id, "unauthorized", message_thread_id=message_thread_id)
                return
        elif self.allowed_user_ids and user_id not in self.allowed_user_ids:
            if self.mode == "managed":
                self.logger.info(
                    "Managed telegram update rejected by allowlist: worker=%s chat_id=%s user_id=%s",
                    self.worker_id,
                    chat_id,
                    user_id,
                )
            self.client.send_message(chat_id, "unauthorized")
            return

        if self.mode == "managed":
            self._send_typing(chat_id, message_thread_id)
            routed = self._route_managed_message(
                text=text,
                chat_type=chat_type,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                user_id=user_id,
            )
            if routed is None:
                return
            if access["should_allow_chat"] and chat_id is not None and self.worker_id is not None:
                try:
                    self.hub.telegram_runtime_manager.allow_managed_chat(self.worker_id, chat_id)
                    self.allowed_chat_ids.add(chat_id)
                    self.logger.info(
                        "Managed telegram chat authorized for worker=%s chat_id=%s by allowed user=%s",
                        self.worker_id,
                        chat_id,
                        user_id,
                    )
                except Exception as exc:
                    self.logger.warning("Failed to persist allowed chat for worker=%s chat_id=%s: %s", self.worker_id, chat_id, exc)
            self.client.send_message(chat_id, routed, message_thread_id=message_thread_id)
            return

        task = HubTask(
            task_id=str(uuid.uuid4()),
            kind="telegram.command",
            payload={
                "command": text,
                "source": "telegram",
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "user_id": user_id,
                "message_id": message.get("message_id"),
            },
        )

        try:
            self._send_typing(chat_id, message_thread_id)
            result = self.hub.submit_and_run_task(task)
            response_text = "ok"
            if isinstance(result, dict):
                response_text = str(result.get("text", result))
            elif isinstance(result, str):
                response_text = result
        except Exception as exc:
            self._last_error = str(exc)
            response_text = f"error: {exc}"

        self.client.send_message(chat_id, response_text, message_thread_id=message_thread_id)

    def _send_typing(self, chat_id: int, message_thread_id: int | None = None) -> None:
        try:
            self.client.send_chat_action(chat_id, "typing", message_thread_id=message_thread_id)
        except Exception:
            pass

    def _route_managed_message(
        self,
        *,
        text: str,
        chat_type: str,
        chat_id: int,
        message_thread_id: int | None,
        user_id: int,
    ) -> str | None:
        if self.worker_id is None:
            self.logger.warning("Managed telegram route missing worker_id for chat_id=%s", chat_id)
            return "managed worker is not configured"

        routed_text = text
        if chat_type in {"group", "supergroup"}:
            if not self.bot_username:
                self.logger.info(
                    "Managed group message ignored because bot username is missing: worker=%s chat_id=%s",
                    self.worker_id,
                    chat_id,
                )
                return None
            mention = f"@{self.bot_username}"
            lowered = text.lower()
            if mention not in lowered:
                self.logger.info(
                    "Managed group message ignored because mention was missing: worker=%s chat_id=%s expected_mention=%s text=%r",
                    self.worker_id,
                    chat_id,
                    mention,
                    text,
                )
                return None
            start = lowered.index(mention)
            end = start + len(mention)
            routed_text = (text[:start] + text[end:]).strip()
            if not routed_text:
                self.logger.info(
                    "Managed group message ignored because mention had no remaining text: worker=%s chat_id=%s mention=%s",
                    self.worker_id,
                    chat_id,
                    mention,
                )
                return None
        elif text in {"/start", "/help"}:
            return f"{self.worker_id} is online. Message normally here, or mention this bot in groups."

        self.logger.info(
            "Managed telegram message routed: worker=%s chat_id=%s user_id=%s chat_type=%s routed_text=%r",
            self.worker_id,
            chat_id,
            user_id,
            chat_type,
            routed_text,
        )
        return self.hub.handle_managed_message(
            worker_id=self.worker_id,
            text=routed_text,
            payload={
                "source": "telegram_managed",
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "user_id": user_id,
                "chat_type": chat_type,
            },
        )

    def _managed_access(self, *, chat_id: int, chat_type: str, user_id: int) -> dict[str, bool]:
        if chat_type in {"group", "supergroup"}:
            if chat_id in self.allowed_chat_ids:
                return {"allowed": True, "should_allow_chat": False}
            if user_id in self.allowed_user_ids:
                return {"allowed": True, "should_allow_chat": True}
            return {"allowed": False, "should_allow_chat": False}
        if not self.allowed_user_ids:
            return {"allowed": True, "should_allow_chat": False}
        return {"allowed": user_id in self.allowed_user_ids, "should_allow_chat": False}


