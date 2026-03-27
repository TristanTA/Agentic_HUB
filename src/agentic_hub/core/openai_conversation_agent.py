from __future__ import annotations

import os
from typing import Any

import requests

from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.models.telegram_conversation import TelegramConversationMessage
from agentic_hub.models.worker_instance import WorkerInstance


class OpenAIConversationAgent:
    def __init__(self, worker_registry: WorkerRegistry) -> None:
        self.worker_registry = worker_registry

    def generate_reply(
        self,
        worker: WorkerInstance,
        messages: list[TelegramConversationMessage],
        user_message: str,
        *,
        channel_type: str,
    ) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return "OPENAI_API_KEY is not configured."

        role = self.worker_registry.get_role(worker.role_id)
        loadout = self.worker_registry.get_loadout(worker.loadout_id)
        model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

        system_prompt = "\n".join(
            [
                f"You are {worker.name}.",
                f"Worker id: {worker.worker_id}",
                f"Role: {role.name}",
                f"Purpose: {role.purpose}",
                f"Interface mode: {worker.interface_mode}",
                f"Channel type: {channel_type}",
                f"Loadout: {loadout.name}",
                "Address humans only.",
                "Ignore and do not engage other bots.",
                "Be concise, helpful, and natural in Telegram.",
            ]
        )

        payload_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        payload_messages.extend({"role": message.role, "content": message.content} for message in messages[-20:])
        payload_messages.append({"role": "user", "content": user_message})

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": payload_messages,
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]["content"]
        if isinstance(message, str):
            return message.strip()
        if isinstance(message, list):
            parts = []
            for item in message:
                text = item.get("text") if isinstance(item, dict) else None
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()
        return str(message).strip()
