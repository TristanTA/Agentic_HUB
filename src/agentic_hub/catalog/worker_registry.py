from __future__ import annotations

from typing import Dict, Iterable

from agentic_hub.models.loadout import Loadout
from agentic_hub.models.memory_policy import MemoryPolicy
from agentic_hub.models.worker_instance import WorkerInstance
from agentic_hub.models.worker_role import WorkerRole
from agentic_hub.models.worker_type import WorkerType


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: Dict[str, WorkerInstance] = {}
        self._types: Dict[str, WorkerType] = {}
        self._roles: Dict[str, WorkerRole] = {}
        self._loadouts: Dict[str, Loadout] = {}
        self._memory_policies: Dict[str, MemoryPolicy] = {}

    def register_type(self, worker_type: WorkerType) -> None:
        if worker_type.type_id in self._types:
            raise ValueError(f"Worker type already registered: {worker_type.type_id}")
        self._types[worker_type.type_id] = worker_type

    def register_role(self, role: WorkerRole) -> None:
        if role.role_id in self._roles:
            raise ValueError(f"Worker role already registered: {role.role_id}")
        self._roles[role.role_id] = role

    def register_loadout(self, loadout: Loadout) -> None:
        if loadout.loadout_id in self._loadouts:
            raise ValueError(f"Loadout already registered: {loadout.loadout_id}")
        self._loadouts[loadout.loadout_id] = loadout

    def register_memory_policy(self, policy: MemoryPolicy) -> None:
        if policy.policy_id in self._memory_policies:
            raise ValueError(f"Memory policy already registered: {policy.policy_id}")
        self._memory_policies[policy.policy_id] = policy

    def register_worker(self, worker: WorkerInstance) -> None:
        if worker.worker_id in self._workers:
            raise ValueError(f"Worker already registered: {worker.worker_id}")
        self._workers[worker.worker_id] = worker

    def get_worker(self, worker_id: str) -> WorkerInstance:
        try:
            return self._workers[worker_id]
        except KeyError as exc:
            raise KeyError(f"Unknown worker_id: {worker_id}") from exc

    def get_type(self, type_id: str) -> WorkerType:
        try:
            return self._types[type_id]
        except KeyError as exc:
            raise KeyError(f"Unknown type_id: {type_id}") from exc

    def get_role(self, role_id: str) -> WorkerRole:
        try:
            return self._roles[role_id]
        except KeyError as exc:
            raise KeyError(f"Unknown role_id: {role_id}") from exc

    def get_loadout(self, loadout_id: str) -> Loadout:
        try:
            return self._loadouts[loadout_id]
        except KeyError as exc:
            raise KeyError(f"Unknown loadout_id: {loadout_id}") from exc

    def get_memory_policy(self, policy_id: str) -> MemoryPolicy:
        try:
            return self._memory_policies[policy_id]
        except KeyError as exc:
            raise KeyError(f"Unknown policy_id: {policy_id}") from exc

    def validate_worker_refs(self, worker_id: str) -> None:
        worker = self.get_worker(worker_id)
        self.get_type(worker.type_id)
        self.get_role(worker.role_id)
        loadout = self.get_loadout(worker.loadout_id)
        if loadout.memory_policy_ref:
            self.get_memory_policy(loadout.memory_policy_ref)

    def list_workers(self) -> list[WorkerInstance]:
        return list(self._workers.values())

    def worker_ids(self) -> Iterable[str]:
        return self._workers.keys()

    def list_types(self) -> list[WorkerType]:
        return list(self._types.values())

    def list_roles(self) -> list[WorkerRole]:
        return list(self._roles.values())

    def list_loadouts(self) -> list[Loadout]:
        return list(self._loadouts.values())

    def list_memory_policies(self) -> list[MemoryPolicy]:
        return list(self._memory_policies.values())

    def clear(self) -> None:
        self._workers.clear()
        self._types.clear()
        self._roles.clear()
        self._loadouts.clear()
        self._memory_policies.clear()

