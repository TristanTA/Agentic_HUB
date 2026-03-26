from __future__ import annotations

from typing import List

from agentic_hub.models.event import HubEvent


class EventLog:
    def __init__(self) -> None:
        self._events: List[HubEvent] = []

    def append(self, event: HubEvent) -> None:
        self._events.append(event)

    def list_all(self) -> List[HubEvent]:
        return list(self._events)

    def list_for_task(self, task_id: str) -> List[HubEvent]:
        return [event for event in self._events if event.task_id == task_id]

    def list_for_worker(self, worker_id: str) -> List[HubEvent]:
        return [event for event in self._events if event.worker_id == worker_id]

