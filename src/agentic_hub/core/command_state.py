from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandSession:
    mode: str
    step: str
    kind: str | None = None
    object_id: str | None = None
    field_name: str | None = None
    draft: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
