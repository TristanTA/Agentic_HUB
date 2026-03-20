from __future__ import annotations

from pathlib import Path

from storage.sqlite.db import SQLiteStore


class LogReader:
    def __init__(self, store: SQLiteStore, human_log_path: Path) -> None:
        self.store = store
        self.human_log_path = human_log_path

    def inspect_recent_errors(self, limit: int = 10) -> list[dict]:
        return self.store.recent_errors(limit=limit)

    def inspect_run_trace(self, run_id: str) -> dict | None:
        return self.store.get_run_trace(run_id)

    def tail_human_log(self, lines: int = 20) -> list[str]:
        if not self.human_log_path.exists():
            return []
        content = self.human_log_path.read_text(encoding="utf-8").splitlines()
        return content[-lines:]
