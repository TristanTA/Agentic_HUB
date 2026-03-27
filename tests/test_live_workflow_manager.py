from __future__ import annotations

import shutil
from pathlib import Path

from agentic_hub.catalog.catalog_manager import CatalogManager
from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.core.approval_manager import ApprovalManager
from agentic_hub.core.artifact_store import ArtifactStore
from agentic_hub.core.event_log import EventLog
from agentic_hub.core.live_agent_worker_adapter import LiveAgentWorkerAdapter
from agentic_hub.core.live_workflow_manager import LiveWorkflowManager
from agentic_hub.core.runtime_coordinator import RuntimeCoordinator


def build_runtime(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "workspace"
    shutil.copytree(repo_root / "content", workspace / "content")
    runtime_dir = workspace / "data" / "runtime"

    worker_registry = WorkerRegistry()
    tool_registry = ToolRegistry()
    catalog_manager = CatalogManager(
        worker_registry,
        tool_registry,
        packs_dir=workspace / "content" / "packs",
        overrides_dir=runtime_dir / "catalog_overrides",
    )
    catalog_manager.reload_catalog()

    approval_manager = ApprovalManager(runtime_dir / "approvals.json")
    artifact_store = ArtifactStore(runtime_dir / "artifacts.json")
    event_log = EventLog(runtime_dir / "events.json")
    coordinator = RuntimeCoordinator(
        worker_registry,
        tool_registry,
        approval_manager=approval_manager,
        artifact_store=artifact_store,
        event_log=event_log,
    )
    adapter = LiveAgentWorkerAdapter(
        worker_registry=worker_registry,
        artifact_store=artifact_store,
        approval_manager=approval_manager,
        repo_root=workspace,
    )
    coordinator.register_adapter("agent_worker", adapter)
    return workspace, runtime_dir, coordinator, artifact_store, approval_manager, adapter


def test_live_workflow_end_to_end(tmp_path, monkeypatch) -> None:
    workspace, runtime_dir, coordinator, artifact_store, approval_manager, adapter = build_runtime(tmp_path)

    monkeypatch.setattr(adapter, "_build_research_context", lambda target_worker_id, objective: {"repo": "context"})
    monkeypatch.setattr(
        adapter,
        "_generate_research_brief",
        lambda worker, target_worker_id, objective, context: {
            "summary": "Research complete",
            "objective": objective,
            "target_workers": [target_worker_id],
            "findings": ["Aria needs a soul file"],
            "recommended_changes": ["Create a soul file"],
            "files_to_create": ["content/packs/basic/worker_docs/aria/soul.md"],
            "files_to_update": [],
            "tools_to_add": [],
            "skills_to_add": [],
            "verification_steps": ["Write-Output verified"],
            "risks": [],
        },
    )
    monkeypatch.setattr(
        adapter,
        "_generate_change_set",
        lambda worker, objective, target_worker_id, research_brief: {
            "summary": "Create Aria soul",
            "file_operations": [
                {
                    "path": "content/packs/basic/worker_docs/aria/soul.md",
                    "action": "create",
                    "reason": "Add soul guidance for Aria",
                    "content": "# Aria Soul\n\nBe concise and operational.\n",
                }
            ],
            "verification_commands": ["Write-Output verified"],
            "risks": [],
        },
    )

    manager = LiveWorkflowManager(
        runtime_coordinator=coordinator,
        artifact_store=artifact_store,
        runtime_dir=runtime_dir,
        repo_root=workspace,
    )

    workflow = manager.start_worker_improvement(target_worker_id="aria", objective="Create a soul file for Aria")
    assert workflow.status == "awaiting_approval"
    assert workflow.approval_id is not None

    approval_manager.approve(workflow.approval_id, approver_id="tester")
    result = manager.resume_approved_workflow(workflow.approval_id)
    assert "Applied change set" in result["message"]

    soul_path = workspace / "content" / "packs" / "basic" / "worker_docs" / "aria" / "soul.md"
    assert soul_path.exists()
    assert "Aria Soul" in soul_path.read_text(encoding="utf-8")

    reloaded_manager = LiveWorkflowManager(
        runtime_coordinator=coordinator,
        artifact_store=artifact_store,
        runtime_dir=runtime_dir,
        repo_root=workspace,
    )
    reloaded = reloaded_manager.get_workflow(workflow.workflow_id)
    assert reloaded.status == "completed"
    assert reloaded.verification_artifact_id is not None
