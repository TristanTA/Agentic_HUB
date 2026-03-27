from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.core.runtime_config import PROJECT_ROOT
from agentic_hub.models.loadout import Loadout
from agentic_hub.models.telegram_conversation import TelegramConversationMessage
from agentic_hub.models.worker_instance import WorkerInstance


class OpenAIConversationAgent:
    def __init__(self, worker_registry: WorkerRegistry, *, skill_library=None) -> None:
        self.worker_registry = worker_registry
        self.skill_library = skill_library

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
        supplemental_context = self._build_loadout_context(loadout, query=user_message)

        system_prompt_parts = [
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
        if supplemental_context:
            system_prompt_parts.append("Supplemental worker context:")
            system_prompt_parts.extend(supplemental_context)

        system_prompt = "\n".join(
            [
                *system_prompt_parts,
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

    def _build_loadout_context(self, loadout: Loadout, *, query: str) -> list[str]:
        parts: list[str] = []
        if loadout.soul_ref:
            soul_text = self._read_ref(loadout.soul_ref)
            if soul_text:
                parts.append(f"Soul:\n{soul_text}")
        for ref in loadout.prompt_refs:
            prompt_text = self._read_ref(ref)
            if prompt_text:
                parts.append(f"Prompt ref {ref}:\n{prompt_text}")
        for ref in loadout.skill_refs:
            skill_text = self._read_ref(ref)
            if skill_text:
                parts.append(f"Skill ref {ref}:\n{skill_text}")
        if self.skill_library is not None:
            for skill in self.skill_library.find_relevant_skills(query, loadout_id=loadout.loadout_id, limit=2):
                skill_text = self._read_ref(skill.body_path)
                if not skill_text:
                    continue
                parts.append(f"Relevant skill {skill.skill_id}:\n{skill_text}")
        return parts

    def _read_ref(self, ref: str) -> str:
        path = (PROJECT_ROOT / ref).resolve() if not Path(ref).is_absolute() else Path(ref).resolve()
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            return ""
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                return raw[:4000]
            if isinstance(payload, dict):
                if "content" in payload:
                    return str(payload["content"])[:4000]
                return json.dumps(payload, indent=2)[:4000]
        return raw[:4000]
