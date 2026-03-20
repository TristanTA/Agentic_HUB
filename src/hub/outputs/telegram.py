from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib import error, parse, request


@dataclass(slots=True)
class TelegramOutputAdapter:
    enabled: bool = True
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"

    def send(self, output_event: dict) -> dict:
        if not self.enabled:
            return {"status": "disabled", "adapter": "telegram", "payload": output_event}

        bot_token = os.getenv(self.bot_token_env, "").strip()
        chat_id = str(output_event.get("thread_id", "")).strip()
        text = str(output_event.get("text", "")).strip()
        if not bot_token:
            return {"status": "skipped", "reason": "missing_bot_token"}
        if not chat_id:
            return {"status": "skipped", "reason": "missing_thread_id"}
        if not text:
            return {"status": "skipped", "reason": "missing_text"}

        payload = {"chat_id": chat_id, "text": text}
        if output_event.get("reply_markup") is not None:
            payload["reply_markup"] = json.dumps(output_event["reply_markup"])
        return self._post_form(bot_token, "sendMessage", payload)

    def send_chat_action(self, thread_id: str, action: str = "typing") -> dict:
        if not self.enabled:
            return {"status": "disabled", "adapter": "telegram"}
        bot_token = os.getenv(self.bot_token_env, "").strip()
        if not bot_token:
            return {"status": "skipped", "reason": "missing_bot_token"}
        return self._post_form(bot_token, "sendChatAction", {"chat_id": thread_id, "action": action})

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> dict:
        if not self.enabled:
            return {"status": "disabled", "adapter": "telegram"}
        bot_token = os.getenv(self.bot_token_env, "").strip()
        if not bot_token:
            return {"status": "skipped", "reason": "missing_bot_token"}
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        return self._post_form(bot_token, "answerCallbackQuery", payload)

    def set_my_commands(self, commands: list[dict[str, str]]) -> dict:
        if not self.enabled:
            return {"status": "disabled", "adapter": "telegram"}
        bot_token = os.getenv(self.bot_token_env, "").strip()
        if not bot_token:
            return {"status": "skipped", "reason": "missing_bot_token"}
        return self._post_form(bot_token, "setMyCommands", {"commands": json.dumps(commands)})

    def _post_form(self, bot_token: str, method: str, payload: dict[str, str]) -> dict:
        data = parse.urlencode(payload).encode("utf-8")
        req = request.Request(
            f"https://api.telegram.org/bot{bot_token}/{method}",
            data=data,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {"status": "error", "reason": f"telegram_http_{exc.code}", "detail": detail, "method": method}
        except error.URLError as exc:
            return {"status": "error", "reason": f"telegram_network_{exc.reason}", "method": method}

        return {"status": "sent", "adapter": "telegram", "method": method, "payload": response_payload}
