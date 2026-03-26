from __future__ import annotations

from agentic_hub.core.approval_manager import ApprovalManager
from agentic_hub.core.artifact_store import ArtifactStore
from agentic_hub.catalog.catalog_manager import CatalogManager
from agentic_hub.core.event_log import EventLog


def build_runtime_status(
    event_log: EventLog,
    artifact_store: ArtifactStore,
    approval_manager: ApprovalManager,
    catalog_manager: CatalogManager | None = None,
) -> str:
    pending = approval_manager.list_pending()
    event_count = len(event_log.list_all())
    approval_artifacts = len(
        [artifact for artifact in artifact_store.list_for_worker("aria") if artifact.kind == "approval_request"]
    )
    catalog_summary: list[str] = []
    if catalog_manager is not None:
        snapshot = catalog_manager.load_effective_catalog()
        catalog_summary = [
            f"- tools: {len(snapshot.tools)}",
            f"- worker types: {len(snapshot.worker_types)}",
            f"- worker roles: {len(snapshot.worker_roles)}",
            f"- loadouts: {len(snapshot.loadouts)}",
            f"- workers: {len(snapshot.workers)}",
        ]

    return "\n".join(
        [
            "runtime status",
            f"- pending approvals: {len(pending)}",
            f"- total events: {event_count}",
            f"- approval artifacts for aria: {approval_artifacts}",
            *catalog_summary,
        ]
    )


