from __future__ import annotations

import json
import os
import time
from pathlib import Path

from hub.models.providers import ModelRegistry
from shared.schemas import ModelSpec
from specs.service import AgentSpecService
from storage.sqlite.db import SQLiteStore


class AgentOSRuntime:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.spec_service = AgentSpecService(root_dir)
        self.store = SQLiteStore(root_dir / "data" / "hub.db")
        self.state_path = root_dir / "data" / "agent_os_state.json"
        self.pid_path = root_dir / "data" / "agent_os.pid"
        self.registry = self.spec_service.load_runtime_registry()
        self.models = ModelRegistry(self._default_models())

    def reload(self) -> None:
        self.registry = self.spec_service.load_runtime_registry()

    def provider_ready(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY", "").strip())

    def status(self) -> dict:
        return {
            "running": self.state_path.exists() and json.loads(self.state_path.read_text(encoding="utf-8")).get("status") == "running",
            "provider_ready": self.provider_ready(),
            "active_agents": [item.id for item in self.registry.agents],
            "registry_path": str(self.spec_service.registry_path.relative_to(self.root_dir)),
        }

    def execute(self, agent_id: str, text: str) -> dict:
        self.reload()
        entry = next((item for item in self.registry.agents if item.id == agent_id), None)
        if entry is None:
            raise ValueError(f"Active agent {agent_id} not found")
        if entry.model_id != "echo_model" and not self.provider_ready():
            raise RuntimeError("Provider unavailable for runtime execution.")
        runnable = self.models.build_runnable(entry.model_id)
        output = runnable.invoke(f"{entry.system_prompt}\n\nCurrent Input:\n{text}")
        return {"agent_id": agent_id, "output_text": str(output)}

    def run_forever(self, sleep_seconds: float = 2.0) -> None:
        self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        while True:
            self.reload()
            self.state_path.write_text(
                json.dumps(
                    {
                        "status": "running",
                        "updated_at": time.time(),
                        "active_agents": [item.id for item in self.registry.agents],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            time.sleep(sleep_seconds)

    def _default_models(self) -> dict[str, ModelSpec]:
        return {
            "openai_gpt5_vanta": ModelSpec(id="openai_gpt5_vanta", provider="openai", model_name="gpt-5.2"),
            "openai_gpt5_mini": ModelSpec(id="openai_gpt5_mini", provider="openai", model_name="gpt-5-mini"),
            "echo_model": ModelSpec(id="echo_model", provider="echo", model_name="echo"),
        }
