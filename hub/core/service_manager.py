from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ManagedService(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def is_running(self) -> bool: ...
    def status(self) -> dict[str, Any]: ...


@dataclass
class ServiceRecord:
    name: str
    service: ManagedService
    kind: str = "persistent"
    state: str = "stopped"  # stopped, running, failed
    started_at: str | None = None
    stopped_at: str | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ServiceManager:
    def __init__(self) -> None:
        self._services: dict[str, ServiceRecord] = {}
        self._lock = threading.RLock()

    def register(self, name: str, service: ManagedService, metadata: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._services[name] = ServiceRecord(
                name=name,
                service=service,
                metadata=metadata or {},
            )

    def start(self, name: str) -> dict[str, Any]:
        with self._lock:
            record = self._services[name]
            if record.service.is_running():
                record.state = "running"
                return {"ok": True, "message": f"{name} already running"}

            try:
                record.service.start()
                record.state = "running"
                record.started_at = utc_now()
                record.last_error = None
                return {"ok": True, "message": f"{name} started"}
            except Exception as exc:
                record.state = "failed"
                record.last_error = str(exc)
                return {"ok": False, "message": f"{name} failed to start", "error": str(exc)}

    def stop(self, name: str) -> dict[str, Any]:
        with self._lock:
            record = self._services[name]
            if not record.service.is_running():
                record.state = "stopped"
                return {"ok": True, "message": f"{name} already stopped"}

            try:
                record.service.stop()
                record.state = "stopped"
                record.stopped_at = utc_now()
                return {"ok": True, "message": f"{name} stopped"}
            except Exception as exc:
                record.state = "failed"
                record.last_error = str(exc)
                return {"ok": False, "message": f"{name} failed to stop", "error": str(exc)}

    def status(self, name: str) -> dict[str, Any]:
        with self._lock:
            record = self._services[name]

            if record.state == "failed":
                live_state = "failed"
            elif record.service.is_running():
                live_state = "running"
            else:
                live_state = record.state

            return {
                "name": record.name,
                "kind": record.kind,
                "state": live_state,
                "started_at": record.started_at,
                "stopped_at": record.stopped_at,
                "last_error": record.last_error,
                "metadata": record.metadata,
                "service_status": record.service.status(),
            }

    def list_status(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self.status(name) for name in self._services]