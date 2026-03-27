from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from agentic_hub.core.runtime_model_store import RuntimeModelStore
from agentic_hub.models.artifact import Artifact


class ArtifactStore:
    def __init__(self, path: Path | None = None) -> None:
        self._artifacts: Dict[str, Artifact] = {}
        self._store = RuntimeModelStore(path, Artifact) if path is not None else None
        if self._store is not None:
            self._artifacts = {artifact.artifact_id: artifact for artifact in self._store.load()}

    def save(self, artifact: Artifact) -> None:
        if artifact.artifact_id in self._artifacts:
            raise ValueError(f"Artifact already exists: {artifact.artifact_id}")
        self._artifacts[artifact.artifact_id] = artifact
        self._flush()

    def get(self, artifact_id: str) -> Artifact:
        try:
            return self._artifacts[artifact_id]
        except KeyError as exc:
            raise KeyError(f"Unknown artifact_id: {artifact_id}") from exc

    def list_all(self) -> List[Artifact]:
        return list(self._artifacts.values())

    def list_for_task(self, task_id: str) -> List[Artifact]:
        return [a for a in self._artifacts.values() if a.task_id == task_id]

    def list_for_worker(self, worker_id: str) -> List[Artifact]:
        return [a for a in self._artifacts.values() if a.worker_id == worker_id]

    def _flush(self) -> None:
        if self._store is None:
            return
        self._store.save(list(self._artifacts.values()))

