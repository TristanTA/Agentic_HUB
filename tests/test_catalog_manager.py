import json
from pathlib import Path

import pytest

from hub.catalog_manager import CatalogManager
from registries.tool_registry import ToolRegistry
from registries.worker_registry import WorkerRegistry


def build_manager(tmp_path: Path) -> CatalogManager:
    repo_root = Path(__file__).resolve().parents[1]
    return CatalogManager(
        WorkerRegistry(),
        ToolRegistry(),
        seed_dir=repo_root / "hub" / "catalog",
        runtime_dir=tmp_path / "runtime_catalog",
    )


def test_startup_loads_seed_catalog(tmp_path) -> None:
    manager = build_manager(tmp_path)

    snapshot = manager.reload_catalog()

    assert any(tool.tool_id == "hub_manage_worker_catalog" for tool in snapshot.tools)
    assert any(worker_type.type_id == "agent_worker" for worker_type in snapshot.worker_types)
    assert any(role.role_id == "operator" for role in snapshot.worker_roles)
    assert any(loadout.loadout_id == "operator_core" for loadout in snapshot.loadouts)
    assert any(worker.worker_id == "aria" for worker in snapshot.workers)


def test_runtime_worker_persists_across_reload(tmp_path) -> None:
    manager = build_manager(tmp_path)
    manager.reload_catalog()

    manager.upsert(
        "workers",
        {
            "worker_id": "nova",
            "name": "Nova",
            "type_id": "agent_worker",
            "role_id": "researcher",
            "loadout_id": "research_core",
        },
    )

    reloaded = build_manager(tmp_path)
    snapshot = reloaded.reload_catalog()
    nova = next(worker for worker in snapshot.workers if worker.worker_id == "nova")

    assert nova.enabled is False
    assert nova.source == "runtime"


def test_runtime_overlay_replaces_seed_worker(tmp_path) -> None:
    manager = build_manager(tmp_path)
    manager.reload_catalog()

    manager.update("workers", "aria", {"enabled": False, "notes": "runtime override"})
    snapshot = manager.load_effective_catalog()
    aria = next(worker for worker in snapshot.workers if worker.worker_id == "aria")

    assert aria.enabled is False
    assert aria.notes == "runtime override"
    assert aria.source == "runtime"


def test_invalid_runtime_update_does_not_persist(tmp_path) -> None:
    manager = build_manager(tmp_path)
    manager.reload_catalog()

    with pytest.raises(ValueError):
        manager.upsert(
            "loadouts",
            {
                "loadout_id": "broken_loadout",
                "name": "Broken",
                "memory_policy_ref": "core_memory",
                "allowed_tool_ids": ["does_not_exist"],
            },
        )

    snapshot = manager.load_effective_catalog()
    assert all(loadout.loadout_id != "broken_loadout" for loadout in snapshot.loadouts)
    runtime_file = tmp_path / "runtime_catalog" / "loadouts.json"
    if runtime_file.exists():
        data = json.loads(runtime_file.read_text(encoding="utf-8"))
        assert all(item["loadout_id"] != "broken_loadout" for item in data)


def test_package_import_and_export(tmp_path) -> None:
    manager = build_manager(tmp_path)
    manager.reload_catalog()

    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    (package_dir / "manifest.json").write_text(
        json.dumps(
            {
                "package_id": "test_pkg",
                "name": "Test Package",
                "version": "1.0.0",
                "description": "test",
                "dependencies": [],
                "conflicts": [],
            }
        ),
        encoding="utf-8",
    )
    (package_dir / "workers.json").write_text(
        json.dumps(
            [
                {
                    "worker_id": "pkg_worker",
                    "name": "Package Worker",
                    "type_id": "agent_worker",
                    "role_id": "operator",
                    "loadout_id": "operator_core",
                    "enabled": False,
                }
            ]
        ),
        encoding="utf-8",
    )

    counts = manager.import_package(package_dir)

    assert counts["workers"] == 1
    snapshot = manager.load_effective_catalog()
    pkg_worker = next(worker for worker in snapshot.workers if worker.worker_id == "pkg_worker")
    assert pkg_worker.package_id == "test_pkg"
    assert pkg_worker.source == "package"

    export_path = tmp_path / "exported_package"
    exported = manager.export_package(export_path)
    assert exported.exists()
    assert (exported / "manifest.json").exists()


def test_package_import_rejects_conflict_and_malformed_json(tmp_path) -> None:
    manager = build_manager(tmp_path)
    manager.reload_catalog()

    conflict_dir = tmp_path / "conflict_pkg"
    conflict_dir.mkdir()
    (conflict_dir / "manifest.json").write_text(
        json.dumps(
            {
                "package_id": "conflict_pkg",
                "name": "Conflict",
                "version": "1.0.0",
                "description": "conflict",
                "dependencies": [],
                "conflicts": [],
            }
        ),
        encoding="utf-8",
    )
    (conflict_dir / "workers.json").write_text(
        json.dumps(
            [
                {
                    "worker_id": "aria",
                    "name": "Duplicate Aria",
                    "type_id": "agent_worker",
                    "role_id": "operator",
                    "loadout_id": "operator_core",
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        manager.import_package(conflict_dir)

    malformed_dir = tmp_path / "bad_pkg"
    malformed_dir.mkdir()
    (malformed_dir / "manifest.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        manager.import_package(malformed_dir)
