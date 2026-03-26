import json
import shutil
from pathlib import Path

import pytest

from agentic_hub.catalog.catalog_manager import CatalogManager
from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry


def build_manager(tmp_path: Path) -> CatalogManager:
    repo_root = Path(__file__).resolve().parents[1]
    packs_dir = tmp_path / "content" / "packs"
    shutil.copytree(repo_root / "content" / "packs" / "basic", packs_dir / "basic", dirs_exist_ok=True)
    return CatalogManager(
        WorkerRegistry(),
        ToolRegistry(),
        packs_dir=packs_dir,
        overrides_dir=tmp_path / "data" / "runtime" / "catalog_overrides",
    )


def make_pack(base_dir: Path, pack_id: str, *, enabled_by_default: bool = True) -> Path:
    pack_dir = base_dir / pack_id
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.json").write_text(
        json.dumps(
            {
                "pack_id": pack_id,
                "name": pack_id,
                "version": "1.0.0",
                "description": pack_id,
                "dependencies": [],
                "conflicts": [],
                "enabled_by_default": enabled_by_default,
            }
        ),
        encoding="utf-8",
    )
    return pack_dir


def write_object(pack_dir: Path, kind: str, object_id: str, payload: dict) -> None:
    folder = pack_dir / kind
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{object_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_basic_pack_loads_successfully(tmp_path) -> None:
    manager = build_manager(tmp_path)

    snapshot = manager.reload_catalog()

    assert any(tool.tool_id == "hub_manage_worker_catalog" for tool in snapshot.tools)
    assert any(worker_type.type_id == "agent_worker" for worker_type in snapshot.worker_types)
    assert any(role.role_id == "operator" for role in snapshot.worker_roles)
    assert any(loadout.loadout_id == "operator_core" for loadout in snapshot.loadouts)
    assert any(worker.worker_id == "aria" for worker in snapshot.workers)


def test_basic_pack_uses_one_file_per_object() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    basic_pack = repo_root / "content" / "packs" / "basic"

    assert (basic_pack / "manifest.json").exists()
    assert (basic_pack / "workers" / "aria.json").exists()
    assert (basic_pack / "tools" / "telegram_send_message.json").exists()
    assert (basic_pack / "loadouts" / "operator_core.json").exists()
    assert (basic_pack / "worker_roles" / "operator.json").exists()
    assert (basic_pack / "worker_types" / "agent_worker.json").exists()
    assert (basic_pack / "memory_policies" / "core_memory.json").exists()


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


def test_runtime_override_replaces_pack_worker(tmp_path) -> None:
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
    runtime_file = tmp_path / "data" / "runtime" / "catalog_overrides" / "loadouts.json"
    if runtime_file.exists():
        data = json.loads(runtime_file.read_text(encoding="utf-8"))
        assert all(item["loadout_id"] != "broken_loadout" for item in data)


def test_package_import_and_export_use_folder_first_format(tmp_path) -> None:
    manager = build_manager(tmp_path)
    manager.reload_catalog()

    package_dir = make_pack(tmp_path, "test_pkg")
    write_object(
        package_dir,
        "workers",
        "pkg_worker",
        {
            "worker_id": "pkg_worker",
            "name": "Package Worker",
            "type_id": "agent_worker",
            "role_id": "operator",
            "loadout_id": "operator_core",
            "enabled": False,
        },
    )

    counts = manager.import_package(package_dir)

    assert counts["workers"] == 1
    snapshot = manager.load_effective_catalog()
    pkg_worker = next(worker for worker in snapshot.workers if worker.worker_id == "pkg_worker")
    assert pkg_worker.package_id == "test_pkg"
    assert pkg_worker.source == "package"

    export_path = tmp_path / "exported_pack"
    exported = manager.export_package(export_path)
    assert exported.exists()
    assert (exported / "manifest.json").exists()
    assert (exported / "workers").exists()


def test_pack_dependency_and_conflict_validation(tmp_path) -> None:
    packs_dir = tmp_path / "packs"
    manager = CatalogManager(
        WorkerRegistry(),
        ToolRegistry(),
        packs_dir=packs_dir,
        overrides_dir=tmp_path / "runtime" / "catalog_overrides",
    )

    alpha = make_pack(packs_dir, "alpha")
    beta = make_pack(packs_dir, "beta")

    (alpha / "manifest.json").write_text(
        json.dumps(
            {
                "pack_id": "alpha",
                "name": "alpha",
                "version": "1.0.0",
                "description": "alpha",
                "dependencies": ["missing_pack"],
                "conflicts": [],
                "enabled_by_default": True,
            }
        ),
        encoding="utf-8",
    )
    (beta / "manifest.json").write_text(
        json.dumps(
            {
                "pack_id": "beta",
                "name": "beta",
                "version": "1.0.0",
                "description": "beta",
                "dependencies": [],
                "conflicts": ["alpha"],
                "enabled_by_default": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        manager.reload_catalog()


def test_cross_pack_duplicate_id_is_rejected(tmp_path) -> None:
    packs_dir = tmp_path / "packs"
    manager = CatalogManager(
        WorkerRegistry(),
        ToolRegistry(),
        packs_dir=packs_dir,
        overrides_dir=tmp_path / "runtime" / "catalog_overrides",
    )

    alpha = make_pack(packs_dir, "alpha")
    beta = make_pack(packs_dir, "beta")
    tool_payload = {
        "tool_id": "shared_tool",
        "name": "Shared Tool",
        "description": "duplicate",
        "implementation_ref": "agentic_hub.services.telegram.tools.send_message",
    }
    write_object(alpha, "tools", "shared_tool", tool_payload)
    write_object(beta, "tools", "shared_tool", tool_payload)

    with pytest.raises(ValueError):
        manager.reload_catalog()
