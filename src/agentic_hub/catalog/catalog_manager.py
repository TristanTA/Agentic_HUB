from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel

from agentic_hub.catalog.catalog_store import CatalogStore
from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.models.loadout import Loadout
from agentic_hub.models.memory_policy import MemoryPolicy
from agentic_hub.models.tool_definition import ToolDefinition
from agentic_hub.models.worker_instance import WorkerInstance
from agentic_hub.models.worker_role import WorkerRole
from agentic_hub.models.worker_type import WorkerType


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
        "tools": ("tools", ToolDefinition, "tool_id"),
        "memory_policies": ("memory_policies", MemoryPolicy, "policy_id"),
        "worker_types": ("worker_types", WorkerType, "type_id"),
        "worker_roles": ("worker_roles", WorkerRole, "role_id"),
        "loadouts": ("loadouts", Loadout, "loadout_id"),
        "workers": ("workers", WorkerInstance, "worker_id"),
    }

    def __init__(
        self,
        worker_registry: WorkerRegistry,
        tool_registry: ToolRegistry,
        *,
        packs_dir: Path | None = None,
        overrides_dir: Path | None = None,
        seed_dir: Path | None = None,
        runtime_dir: Path | None = None,
    ) -> None:
        self.worker_registry = worker_registry
        self.tool_registry = tool_registry
        self.packs_dir = packs_dir or seed_dir
        self.overrides_dir = overrides_dir or runtime_dir
        if self.packs_dir is None or self.overrides_dir is None:
            raise TypeError("CatalogManager requires packs_dir/overrides_dir or seed_dir/runtime_dir")
        self.override_stores = {
            name: CatalogStore(self.overrides_dir / f"{name}.json", model_cls)
            for name, (_, model_cls, _) in self.FILES.items()
        }

    def load_effective_catalog(self) -> CatalogSnapshot:
        return self._build_snapshot(self._load_enabled_packs(), self._load_override_data())

    def reload_catalog(self) -> CatalogSnapshot:
        snapshot = self.load_effective_catalog()
        self._activate_snapshot(snapshot)
        return snapshot

    def build_runtime_snapshot(self) -> CatalogSnapshot:
        overrides = self._load_override_data()
        return CatalogSnapshot(
            tools=overrides["tools"],
            memory_policies=overrides["memory_policies"],
            worker_types=overrides["worker_types"],
            worker_roles=overrides["worker_roles"],
            loadouts=overrides["loadouts"],
            workers=overrides["workers"],
        )

    def list_objects(self, kind: str) -> list[BaseModel]:
        if kind not in self.FILES:
            raise ValueError(f"Unknown catalog kind: {kind}")
        snapshot = self.load_effective_catalog()
        return list(getattr(snapshot, kind))

    def upsert(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        source: str = "runtime",
        package_id: str | None = None,
    ) -> str:
        if kind not in self.FILES:
            raise ValueError(f"Unknown catalog kind: {kind}")

        _, model_cls, key_attr = self.FILES[kind]
        runtime_snapshot = self.build_runtime_snapshot()
        runtime_items = list(getattr(runtime_snapshot, kind))

        data = dict(payload)
        data["source"] = source
        data["package_id"] = package_id
        data["updated_at"] = utc_now()
        if kind == "workers":
            data.setdefault("enabled", False)

        item = model_cls.model_validate(data)
        key = getattr(item, key_attr)

        updated = [existing for existing in runtime_items if getattr(existing, key_attr) != key]
        updated.append(item)

        override_data = self._load_override_data()
        override_data[kind] = updated
        effective = self._build_snapshot(self._load_enabled_packs(), override_data)
        self.override_stores[kind].save(updated)
        self._activate_snapshot(effective)
        return str(key)

    def update(self, kind: str, object_id: str, updates: dict[str, Any]) -> None:
        if kind not in self.FILES:
            raise ValueError(f"Unknown catalog kind: {kind}")

        combined = {self._item_key(kind, item): item for item in self.list_objects(kind)}
        try:
            current = combined[object_id]
        except KeyError as exc:
            raise KeyError(f"Unknown {kind} id: {object_id}") from exc

        payload = current.model_dump(mode="python")
        payload.update(updates)
        self.upsert(kind, payload, source="runtime", package_id=None)

    def set_enabled(self, kind: str, object_id: str, enabled: bool) -> None:
        self.update(kind, object_id, {"enabled": enabled})

    def assign_worker(self, worker_id: str, field_name: str, value: str) -> None:
        if field_name not in {"type_id", "role_id", "loadout_id"}:
            raise ValueError(f"Unsupported worker assignment field: {field_name}")
        self.update("workers", worker_id, {field_name: value})

    def dependency_summary(self, kind: str, object_id: str) -> list[str]:
        snapshot = self.load_effective_catalog()
        if kind == "tools":
            loadouts = [item.loadout_id for item in snapshot.loadouts if object_id in item.allowed_tool_ids]
            return [f"used by loadouts: {', '.join(loadouts)}"] if loadouts else []
        if kind == "worker_roles":
            workers = [item.worker_id for item in snapshot.workers if item.role_id == object_id]
            return [f"used by workers: {', '.join(workers)}"] if workers else []
        if kind == "worker_types":
            workers = [item.worker_id for item in snapshot.workers if item.type_id == object_id]
            return [f"used by workers: {', '.join(workers)}"] if workers else []
        if kind == "loadouts":
            workers = [item.worker_id for item in snapshot.workers if item.loadout_id == object_id]
            return [f"used by workers: {', '.join(workers)}"] if workers else []
        if kind == "memory_policies":
            loadouts = [item.loadout_id for item in snapshot.loadouts if item.memory_policy_ref == object_id]
            return [f"used by loadouts: {', '.join(loadouts)}"] if loadouts else []
        return []

    def delete(self, kind: str, object_id: str) -> None:
        if kind not in self.FILES:
            raise ValueError(f"Unknown catalog kind: {kind}")

        dependencies = self.dependency_summary(kind, object_id)
        if dependencies and kind not in {"workers"}:
            raise ValueError(f"Cannot delete {kind} {object_id}: {'; '.join(dependencies)}")

        _, _, key_attr = self.FILES[kind]
        runtime_items = self.override_stores[kind].load()
        remaining = [item for item in runtime_items if getattr(item, key_attr) != object_id]
        if len(remaining) != len(runtime_items):
            self.override_stores[kind].save(remaining)
            self.reload_catalog()
            return

        current_ids = {self._item_key(kind, item) for item in self.list_objects(kind)}
        if object_id not in current_ids:
            raise KeyError(f"Unknown {kind} id: {object_id}")

        if kind in {"workers", "tools"}:
            self.set_enabled(kind, object_id, False)
            return

        raise ValueError(
            f"Cannot delete pack-managed {kind} {object_id}; create a runtime override or remove dependents first"
        )

    def export_package(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        runtime_snapshot = self.build_runtime_snapshot()
        manifest = {
            "pack_id": destination.stem,
            "name": destination.stem,
            "version": "1.0.0",
            "description": "Exported runtime overrides pack.",
            "dependencies": [],
            "conflicts": [],
            "enabled_by_default": False,
        }

        if destination.suffix.lower() == ".zip":
            with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest, indent=2))
                for kind, (folder_name, _, _) in self.FILES.items():
                    for item in getattr(runtime_snapshot, kind):
                        archive.writestr(
                            f"{folder_name}/{self._item_key(kind, item)}.json",
                            json.dumps(item.model_dump(mode="json"), indent=2),
                        )
            return destination

        destination.mkdir(parents=True, exist_ok=True)
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for kind, (folder_name, _, _) in self.FILES.items():
            folder = destination / folder_name
            folder.mkdir(parents=True, exist_ok=True)
            for item in getattr(runtime_snapshot, kind):
                item_path = folder / f"{self._item_key(kind, item)}.json"
                item_path.write_text(json.dumps(item.model_dump(mode="json"), indent=2), encoding="utf-8")
        return destination

    def import_package(self, package_path: Path, *, allow_override: bool = False) -> dict[str, int]:
        package_data = self._read_package(package_path)
        manifest = package_data["manifest"]
        pack_id = self._manifest_pack_id(manifest)
        destination = self.packs_dir / pack_id

        if destination.exists():
            if not allow_override:
                raise ValueError(f"Package already exists: {pack_id}")
            shutil.rmtree(destination)

        destination.mkdir(parents=True, exist_ok=True)
        self._write_package_dir(destination, package_data)

        try:
            self.reload_catalog()
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

        return {kind: len(package_data.get(kind, [])) for kind in self.FILES}

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

    def _load_enabled_packs(self) -> dict[str, list[BaseModel]]:
        merged: dict[str, dict[str, BaseModel]] = {kind: {} for kind in self.FILES}
        manifests: dict[str, dict[str, Any]] = {}
        pack_contents: dict[str, dict[str, list[BaseModel]]] = {}

        if self.packs_dir.exists():
            for pack_dir in sorted(path for path in self.packs_dir.iterdir() if path.is_dir()):
                package_data = self._read_package_dir(pack_dir)
                manifest = package_data["manifest"]
                if not manifest.get("enabled_by_default", True):
                    continue
                pack_id = self._manifest_pack_id(manifest)
                manifests[pack_id] = manifest
                pack_contents[pack_id] = {kind: package_data.get(kind, []) for kind in self.FILES}

        self._validate_pack_relationships(manifests)

        for pack_id in sorted(pack_contents):
            for kind in self.FILES:
                for item in pack_contents[pack_id][kind]:
                    key = self._item_key(kind, item)
                    if key in merged[kind]:
                        raise ValueError(f"Duplicate {kind} id across packs: {key}")
                    merged[kind][key] = item

        return {kind: list(items.values()) for kind, items in merged.items()}

    def _load_override_data(self) -> dict[str, list[BaseModel]]:
        return {kind: store.load() for kind, store in self.override_stores.items()}

    def _build_snapshot(
        self,
        pack_data: dict[str, list[BaseModel]],
        override_data: dict[str, list[BaseModel]],
    ) -> CatalogSnapshot:
        merged = {
            kind: self._merge_items(pack_data[kind], override_data[kind], kind)
            for kind in self.FILES
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

    def _merge_items(self, pack_items: list[BaseModel], runtime_items: list[BaseModel], kind: str) -> list[BaseModel]:
        _, _, key_attr = self.FILES[kind]
        merged: dict[str, BaseModel] = {}
        for item in pack_items + runtime_items:
            merged[str(getattr(item, key_attr))] = item
        return list(merged.values())

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

    def _read_package(self, package_path: Path) -> dict[str, object]:
        if package_path.is_file() and package_path.suffix.lower() == ".zip":
            return self._read_package_zip(package_path)
        return self._read_package_dir(package_path)

    def _read_package_dir(self, package_dir: Path) -> dict[str, object]:
        manifest_path = package_dir / "manifest.json"
        if not manifest_path.exists():
            raise ValueError("Package missing manifest.json")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        pack_id = self._manifest_pack_id(manifest)
        data: dict[str, object] = {"manifest": manifest}
        for kind, (folder_name, model_cls, _) in self.FILES.items():
            folder = package_dir / folder_name
            items = []
            if folder.exists():
                for item_path in sorted(folder.glob("*.json")):
                    raw_item = json.loads(item_path.read_text(encoding="utf-8-sig"))
                    items.append(self._validate_package_item(model_cls, raw_item, pack_id))
            data[kind] = items
        return data

    def _read_package_zip(self, package_path: Path) -> dict[str, object]:
        data: dict[str, object] = {}
        with ZipFile(package_path, "r") as archive:
            names = set(archive.namelist())
            if "manifest.json" not in names:
                raise ValueError("Package missing manifest.json")
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            pack_id = self._manifest_pack_id(manifest)
            data["manifest"] = manifest
            for kind, (folder_name, model_cls, _) in self.FILES.items():
                prefix = f"{folder_name}/"
                items = []
                for name in sorted(entry for entry in names if entry.startswith(prefix) and entry.endswith(".json")):
                    raw_item = json.loads(archive.read(name).decode("utf-8"))
                    items.append(self._validate_package_item(model_cls, raw_item, pack_id))
                data[kind] = items
        return data

    def _write_package_dir(self, destination: Path, package_data: dict[str, object]) -> None:
        manifest = dict(package_data["manifest"])
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        for kind, (folder_name, _, _) in self.FILES.items():
            folder = destination / folder_name
            folder.mkdir(parents=True, exist_ok=True)
            for item in package_data.get(kind, []):
                payload = item.model_dump(mode="json")
                payload["source"] = "package"
                payload["package_id"] = self._manifest_pack_id(manifest)
                item_id = self._item_key(kind, item)
                (folder / f"{item_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _validate_package_item(self, model_cls: type[BaseModel], raw_item: dict[str, Any], pack_id: str) -> BaseModel:
        data = dict(raw_item)
        data["source"] = "package"
        data["package_id"] = pack_id
        data.setdefault("updated_at", utc_now())
        return model_cls.model_validate(data)

    def _validate_pack_relationships(self, manifests: dict[str, dict[str, Any]]) -> None:
        pack_ids = set(manifests)
        for pack_id, manifest in manifests.items():
            for dependency in manifest.get("dependencies", []):
                if dependency not in pack_ids:
                    raise ValueError(f"Pack {pack_id} depends on missing pack {dependency}")
            for conflict in manifest.get("conflicts", []):
                if conflict in pack_ids:
                    raise ValueError(f"Pack {pack_id} conflicts with installed pack {conflict}")

    def _manifest_pack_id(self, manifest: dict[str, Any]) -> str:
        return str(manifest.get("pack_id") or manifest.get("package_id"))

    def _item_key(self, kind: str, item: object) -> str:
        return str(getattr(item, self.FILES[kind][2]))
