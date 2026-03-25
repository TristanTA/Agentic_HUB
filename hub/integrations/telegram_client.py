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

    def send_message(self, chat_id: int, text: str) -> dict:
        r = requests.post(
            f"{self.base_url}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()