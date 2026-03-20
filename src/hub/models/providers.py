from __future__ import annotations

from langchain_core.runnables import RunnableLambda

from shared.schemas import ModelSpec


class ModelRegistry:
    def __init__(self, models: dict[str, ModelSpec]) -> None:
        self.models = models

    def build_runnable(self, model_id: str):
        spec = self.models[model_id]

        def invoke(payload):
            if isinstance(payload, str):
                text = payload
            elif isinstance(payload, dict):
                text = payload.get("input") or payload.get("text") or str(payload)
            else:
                text = str(payload)
            return f"[{spec.model_name}] {text}"

        return RunnableLambda(invoke)
