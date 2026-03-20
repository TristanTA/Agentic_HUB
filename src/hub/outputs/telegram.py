from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TelegramOutputAdapter:
    enabled: bool = True

    def send(self, output_event: dict) -> dict:
        return {"status": "queued", "adapter": "telegram", "payload": output_event}
