from __future__ import annotations

from pathlib import Path
from typing import List

from agentic_hub.core.runtime_model_store import RuntimeModelStore
from agentic_hub.models.event import HubEvent


class EventLog:
    def __init__(self, path: Path | None = None) -> None:
        self._events: List[HubEvent] = []
        self._store = RuntimeModelStore(path, HubEvent) if path is not None else None
        if self._store is not None:
            self._events = self._store.load()

    def append(self, event: HubEvent) -> None:
        self._events.append(event)
        self._flush()

    def list_all(self) -> List[HubEvent]:
        return list(self._events)

    def list_for_task(self, task_id: str) -> List[HubEvent]:
        return [event for event in self._events if event.task_id == task_id]

    def list_for_worker(self, worker_id: str) -> List[HubEvent]:
        return [event for event in self._events if event.worker_id == worker_id]

    def _flush(self) -> None:
        if self._store is None:
            return
        self._store.save(self._events)

