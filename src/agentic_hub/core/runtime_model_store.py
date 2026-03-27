from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)


class RuntimeModelStore:
    def __init__(self, path: Path, model_cls: type[ModelT]) -> None:
        self.path = path
        self.model_cls = model_cls

    def load(self) -> list[ModelT]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"Runtime store must contain a list: {self.path}")
        return [self.model_cls.model_validate(item) for item in raw]

    def save(self, items: list[ModelT]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.model_dump(mode="json") for item in items]
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
