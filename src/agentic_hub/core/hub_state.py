from dataclasses import dataclass
from typing import Optional
import json
from pathlib import Path


@dataclass
class HubState:
    status: str = "stopped"
    run_id: Optional[str] = None
    stop_requested: bool = False
    last_error: Optional[str] = None

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2))