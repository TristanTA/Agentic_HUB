import json
from pathlib import Path

from hub.tasks import Task


class TaskStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[Task]:
        if not self.path.exists():
            return []

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [Task.from_dict(item) for item in raw]

    def save(self, tasks: list[Task]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [task.to_dict() for task in tasks]
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")