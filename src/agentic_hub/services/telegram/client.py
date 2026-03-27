from __future__ import annotations

import requests


class TelegramClient:
    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    def get_updates(self, offset: int | None = None, timeout: int = 20) -> dict:
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        r = requests.get(f"{self.base_url}/getUpdates", params=params, timeout=timeout + 5)
        r.raise_for_status()
        return r.json()

    def send_message(self, chat_id: int, text: str, *, message_thread_id: int | None = None) -> dict:
        payload = {"chat_id": chat_id, "text": text}
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        r = requests.post(
            f"{self.base_url}/sendMessage",
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def send_chat_action(self, chat_id: int, action: str = "typing", *, message_thread_id: int | None = None) -> dict:
        payload = {"chat_id": chat_id, "action": action}
        if message_thread_id is not None:
            payload["message_thread_id"] = message_thread_id
        r = requests.post(
            f"{self.base_url}/sendChatAction",
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def set_my_commands(self, commands: list[dict[str, str]]) -> dict:
        r = requests.post(
            f"{self.base_url}/setMyCommands",
            json={"commands": commands},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def set_message_reaction(self, chat_id: int, message_id: int, emoji: str, *, is_big: bool = False) -> dict:
        r = requests.post(
            f"{self.base_url}/setMessageReaction",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reaction": [{"type": "emoji", "emoji": emoji}],
                "is_big": is_big,
            },
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    def get_me(self) -> dict:
        r = requests.get(f"{self.base_url}/getMe", timeout=15)
        r.raise_for_status()
        return r.json()
