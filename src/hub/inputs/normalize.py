from __future__ import annotations

from shared.schemas import NormalizedEvent


def normalize_telegram_payload(payload: dict) -> NormalizedEvent:
    message = payload.get("message", {})
    chat = message.get("chat", {})
    text = message.get("text", "") or payload.get("text", "")
    external_id = str(message.get("message_id", payload.get("update_id", "local-event")))
    thread_id = str(chat.get("id", payload.get("thread_id", "local-thread")))
    return NormalizedEvent(
        source="telegram",
        external_id=external_id,
        thread_id=thread_id,
        user_payload=payload,
        text=text,
        metadata={"chat": chat},
    )
