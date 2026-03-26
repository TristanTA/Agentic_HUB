from __future__ import annotations

from typing import Dict, List

from agentic_hub.models.artifact import Artifact


class ArtifactStore:
    def __init__(self) -> None:
        self._artifacts: Dict[str, Artifact] = {}

    def save(self, artifact: Artifact) -> None:
        if artifact.artifact_id in self._artifacts:
            raise ValueError(f"Artifact already exists: {artifact.artifact_id}")
        self._artifacts[artifact.artifact_id] = artifact

    def get(self, artifact_id: str) -> Artifact:
        try:
            return self._artifacts[artifact_id]
        except KeyError as exc:
            raise KeyError(f"Unknown artifact_id: {artifact_id}") from exc

    def list_for_task(self, task_id: str) -> List[Artifact]:
        return [a for a in self._artifacts.values() if a.task_id == task_id]

    def list_for_worker(self, worker_id: str) -> List[Artifact]:
        return [a for a in self._artifacts.values() if a.worker_id == worker_id]

