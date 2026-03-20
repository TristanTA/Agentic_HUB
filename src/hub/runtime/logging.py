from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class StructuredLogger:
    def __init__(self, structured_path: Path, human_path: Path) -> None:
        self.structured_path = structured_path
        self.human_path = human_path
        self.structured_path.parent.mkdir(parents=True, exist_ok=True)
        self.human_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event_type: str, payload: dict[str, Any]) -> None:
        structured_line = json.dumps({"event_type": event_type, **payload}, default=str)
        if self.structured_path.exists():
            current_structured = self.structured_path.read_text(encoding="utf-8")
        else:
            current_structured = ""
        self.structured_path.write_text(current_structured + structured_line + "\n", encoding="utf-8")
        if self.human_path.exists():
            current_human = self.human_path.read_text(encoding="utf-8")
        else:
            current_human = ""
        self.human_path.write_text(current_human + f"{event_type}: {payload}\n", encoding="utf-8")
