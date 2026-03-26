from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from pydantic import BaseModel

from hub.catalog_store import CatalogStore
from registries.tool_registry import ToolRegistry
from registries.worker_registry import WorkerRegistry
from schemas.loadout import Loadout
from schemas.memory_policy import MemoryPolicy
from schemas.tool_definition import ToolDefinition
from schemas.worker_instance import WorkerInstance
from schemas.worker_role import WorkerRole
from schemas.worker_type import WorkerType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class CatalogSnapshot:
    tools: list[ToolDefinition]
    memory_policies: list[MemoryPolicy]
    worker_types: list[WorkerType]
    worker_roles: list[WorkerRole]
    loadouts: list[Loadout]
    workers: list[WorkerInstance]


class CatalogManager:
    FILES = {
        "tools": ("tools.json", ToolDefinition, "tool_id"),
        "memory_policies": ("memory_policies.json", MemoryPolicy, "policy_id"),
        "worker_types": ("worker_types.json", WorkerType, "type_id"),
        "worker_roles": ("worker_roles.json", WorkerRole, "role_id"),
        "loadouts": ("loadouts.json", Loadout, "loadout_id"),
        "workers": ("workers.json", WorkerInstance, "worker_id"),
    }

    def __init__(
        self,
        worker_registry: WorkerRegistry,
        tool_registry: ToolRegistry,
        *,
        seed_dir: Path,
        runtime_dir: Path,
    ) -> None:
        self.worker_registry = worker_registry
        self.tool_registry = tool_registry
        self.seed_dir = seed_dir
        self.runtime_dir = runtime_dir
        self.seed_stores = self._build_stores(seed_dir)
        self.runtime_stores = self._build_stores(runtime_dir)

    def _build_stores(self, root: Path) -> dict[str, CatalogStore]:
        return {
            name: CatalogStore(root / filename, model_cls)
            for name, (filename, model_cls, _) in self.FILES.items()
        }

    def load_effective_catalog(self) -> CatalogSnapshot:
        seed = {name: store.load() for name, store in self.seed_stores.items()}
        runtime = {name: store.load() for name, store in self.runtime_stores.items()}
        return self._build_snapshot(seed, runtime)

    def reload_catalog(self) -> CatalogSnapshot:
        snapshot = self.load_effective_catalog()
        self._activate_snapshot(snapshot)
        return snapshot

    def _build_snapshot(
        self,
        seed_data: dict[str, list[object]],
        runtime_data: dict[str, list[object]],
    ) -> CatalogSnapshot:
        merged = {
            name: self._merge_items(seed_data[name], runtime_data[name], name)
            for name in self.FILES
        }

        snapshot = CatalogSnapshot(
            tools=merged["tools"],
            memory_policies=merged["memory_policies"],
            worker_types=merged["worker_types"],
            worker_roles=merged["worker_roles"],
            loadouts=merged["loadouts"],
            workers=merged["workers"],
        )
        self.validate_catalog(snapshot)
        return snapshot

    def _merge_items(self, seed_items: list[object], runtime_items: list[object], kind: str) -> list[object]:
        _, _, key_attr = self.FILES[kind]
        merged: dict[str, object] = {}
        for item in seed_items + runtime_items:
            merged[getattr(item, key_attr)] = item
        return list(merged.values())

    def validate_catalog(self, snapshot: CatalogSnapshot) -> None:
        tool_ids = {item.tool_id for item in snapshot.tools}
        memory_policy_ids = {item.policy_id for item in snapshot.memory_policies}
        worker_type_ids = {item.type_id for item in snapshot.worker_types}
        worker_role_ids = {item.role_id for item in snapshot.worker_roles}
        loadout_ids = {item.loadout_id for item in snapshot.loadouts}

        for loadout in snapshot.loadouts:
            if loadout.memory_policy_ref and loadout.memory_policy_ref not in memory_policy_ids:
                raise ValueError(f"Unknown memory policy for loadout {loadout.loadout_id}: {loadout.memory_policy_ref}")
            for tool_id in loadout.allowed_tool_ids:
                if tool_id not in tool_ids:
                    raise ValueError(f"Unknown tool for loadout {loadout.loadout_id}: {tool_id}")
            for tool_id in loadout.tool_policy_overrides:
                if tool_id not in tool_ids:
                    raise ValueError(f"Unknown tool override for loadout {loadout.loadout_id}: {tool_id}")

        for worker in snapshot.workers:
            if worker.type_id not in worker_type_ids:
                raise ValueError(f"Unknown worker type for worker {worker.worker_id}: {worker.type_id}")
            if worker.role_id not in worker_role_ids:
                raise ValueError(f"Unknown worker role for worker {worker.worker_id}: {worker.role_id}")
            if worker.loadout_id not in loadout_ids:
                raise ValueError(f"Unknown loadout for worker {worker.worker_id}: {worker.loadout_id}")

    def _activate_snapshot(self, snapshot: CatalogSnapshot) -> None:
        self.tool_registry.clear()
        self.worker_registry.clear()

        for tool in snapshot.tools:
            self.tool_registry.register(tool)
        for memory_policy in snapshot.memory_policies:
            self.worker_registry.register_memory_policy(memory_policy)
        for worker_type in snapshot.worker_types:
            self.worker_registry.register_type(worker_type)
        for worker_role in snapshot.worker_roles:
            self.worker_registry.register_role(worker_role)
        for loadout in snapshot.loadouts:
            self.worker_registry.register_loadout(loadout)
        for worker in snapshot.workers:
            self.worker_registry.register_worker(worker)
            self.worker_registry.validate_worker_refs(worker.worker_id)

    def build_runtime_snapshot(self) -> CatalogSnapshot:
        return CatalogSnapshot(
            tools=self.runtime_stores["tools"].load(),
            memory_policies=self.runtime_stores["memory_policies"].load(),
            worker_types=self.runtime_stores["worker_types"].load(),
            worker_roles=self.runtime_stores["worker_roles"].load(),
            loadouts=self.runtime_stores["loadouts"].load(),
            workers=self.runtime_stores["workers"].load(),
        )

    def list_objects(self, kind: str) -> list[BaseModel]:
        if kind not in self.FILES:
            raise ValueError(f"Unknown catalog kind: {kind}")
        snapshot = self.load_effective_catalog()
        return list(getattr(snapshot, kind))

    def upsert(self, kind: str, payload: dict[str, Any], *, source: str = "runtime", package_id: str | None = None) -> str:
        if kind not in self.FILES:
            raise ValueError(f"Unknown catalog kind: {kind}")

        snapshot = self.build_runtime_snapshot()
        items = list(getattr(snapshot, kind))
        _, model_cls, key_attr = self.FILES[kind]

        data = dict(payload)
        data["source"] = source
        data["package_id"] = package_id
        data["updated_at"] = utc_now()
        if kind == "workers":
            data.setdefault("enabled", False)
        item = model_cls.model_validate(data)
        key = getattr(item, key_attr)

        updated = [existing for existing in items if getattr(existing, key_attr) != key]
        updated.append(item)

        candidate = self.build_runtime_snapshot()
        setattr(candidate, kind, updated)
        effective = self._build_snapshot(
            {name: store.load() for name, store in self.seed_stores.items()},
            {
                "tools": candidate.tools,
                "memory_policies": candidate.memory_policies,
                "worker_types": candidate.worker_types,
                "worker_roles": candidate.worker_roles,
                "loadouts": candidate.loadouts,
                "workers": candidate.workers,
            },
        )
        self.runtime_stores[kind].save(updated)
        self._activate_snapshot(effective)
        return str(key)

    def update(self, kind: str, object_id: str, updates: dict) -> None:
        if kind not in self.FILES:
            raise ValueError(f"Unknown catalog kind: {kind}")
        runtime_items = self.runtime_stores[kind].load()
        _, _, key_attr = self.FILES[kind]

        combined = {getattr(item, key_attr): item for item in self.list_objects(kind)}
        try:
            current = combined[object_id]
        except KeyError as exc:
            raise KeyError(f"Unknown {kind} id: {object_id}") from exc

        payload = current.model_dump(mode="python")
        payload.update(updates)
        payload["updated_at"] = utc_now()
        package_id = payload.get("package_id")
        source = "package" if package_id else "runtime"
        self.upsert(kind, payload, source=source, package_id=package_id)

    def set_enabled(self, kind: str, object_id: str, enabled: bool) -> None:
        self.update(kind, object_id, {"enabled": enabled})

    def assign_worker(self, worker_id: str, field_name: str, value: str) -> None:
        if field_name not in {"type_id", "role_id", "loadout_id"}:
            raise ValueError(f"Unsupported worker assignment field: {field_name}")
        self.update("workers", worker_id, {field_name: value})

    def export_package(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        runtime_snapshot = self.build_runtime_snapshot()
        manifest = {
            "package_id": destination.stem,
            "name": destination.stem,
            "version": "1.0.0",
            "description": "Exported runtime catalog package.",
            "dependencies": [],
            "conflicts": [],
        }
        if destination.suffix.lower() == ".zip":
            with ZipFile(destination, "w") as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                for kind, (filename, _, _) in self.FILES.items():
                    archive.writestr(filename, json.dumps([
                        item.model_dump(mode="json") for item in getattr(runtime_snapshot, kind)
                    ], indent=2))
            return destination

        destination.mkdir(parents=True, exist_ok=True)
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for kind, (filename, _, _) in self.FILES.items():
            payload = [item.model_dump(mode="json") for item in getattr(runtime_snapshot, kind)]
            (destination / filename).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return destination

    def import_package(self, package_path: Path, *, allow_override: bool = False) -> dict[str, int]:
        package_data = self._read_package(package_path)
        manifest = package_data["manifest"]
        package_id = manifest["package_id"]

        current_effective = {
            kind: {self._item_key(kind, item): item for item in self.list_objects(kind)}
            for kind in self.FILES
        }
        runtime_snapshot = self.build_runtime_snapshot()
        runtime_data = {
            "tools": list(runtime_snapshot.tools),
            "memory_policies": list(runtime_snapshot.memory_policies),
            "worker_types": list(runtime_snapshot.worker_types),
            "worker_roles": list(runtime_snapshot.worker_roles),
            "loadouts": list(runtime_snapshot.loadouts),
            "workers": list(runtime_snapshot.workers),
        }

        counts: dict[str, int] = {}
        for kind, (_, model_cls, key_attr) in self.FILES.items():
            raw_items = package_data.get(kind, [])
            imported_items = []
            for raw_item in raw_items:
                data = dict(raw_item)
                data["source"] = "package"
                data["package_id"] = package_id
                data["updated_at"] = utc_now()
                item = model_cls.model_validate(data)
                key = getattr(item, key_attr)
                if key in current_effective[kind] and not allow_override:
                    raise ValueError(f"Package conflict for {kind}: {key}")
                imported_items.append(item)

            if imported_items:
                existing = {
                    getattr(item, key_attr): item for item in runtime_data[kind]
                }
                for item in imported_items:
                    existing[getattr(item, key_attr)] = item
                runtime_data[kind] = list(existing.values())
            counts[kind] = len(imported_items)

        effective = self._build_snapshot(
            {name: store.load() for name, store in self.seed_stores.items()},
            runtime_data,
        )
        for kind in self.FILES:
            self.runtime_stores[kind].save(runtime_data[kind])
        self._activate_snapshot(effective)
        return counts

    def _read_package(self, package_path: Path) -> dict[str, object]:
        if not package_path.exists():
            raise FileNotFoundError(package_path)

        data: dict[str, object] = {}
        filenames = {name: spec[0] for name, spec in self.FILES.items()}
        if package_path.is_file() and package_path.suffix.lower() == ".zip":
            with ZipFile(package_path, "r") as archive:
                names = set(archive.namelist())
                if "manifest.json" not in names:
                    raise ValueError("Package missing manifest.json")
                data["manifest"] = json.loads(archive.read("manifest.json").decode("utf-8"))
                for kind, filename in filenames.items():
                    data[kind] = json.loads(archive.read(filename).decode("utf-8")) if filename in names else []
            return data

        manifest_path = package_path / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("Package missing manifest.json")
        data["manifest"] = json.loads(manifest_path.read_text(encoding="utf-8"))
        for kind, filename in filenames.items():
            file_path = package_path / filename
            data[kind] = json.loads(file_path.read_text(encoding="utf-8")) if file_path.exists() else []
        return data

    def _item_key(self, kind: str, item: object) -> str:
        return str(getattr(item, self.FILES[kind][2]))
