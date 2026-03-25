import json
from pathlib import Path

from hub.tasks import DeadTaskRecord


class DeadTaskStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[DeadTaskRecord]:
        if not self.path.exists():
            return []

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return [DeadTaskRecord.from_dict(item) for item in raw]

    def append(self, record: DeadTaskRecord) -> None:
        records = self.load()
        records.append(record)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = [item.to_dict() for item in records]
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")