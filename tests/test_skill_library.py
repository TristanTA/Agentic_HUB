from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from agentic_hub.catalog.catalog_manager import CatalogManager
from agentic_hub.catalog.tool_registry import ToolRegistry
from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.core.skill_library import SkillLibrary


def build_library(tmp_path: Path) -> SkillLibrary:
    repo_root = Path(__file__).resolve().parents[1]
    catalog_manager = CatalogManager(
        WorkerRegistry(),
        ToolRegistry(),
        packs_dir=repo_root / "content" / "packs",
        overrides_dir=tmp_path / "catalog_overrides",
    )
    catalog_manager.reload_catalog()
    return SkillLibrary(runtime_dir=tmp_path, repo_root=repo_root, catalog_manager=catalog_manager)


def test_repeated_demand_accumulates_and_unrelated_requests_do_not_merge(tmp_path) -> None:
    library = build_library(tmp_path)

    first = library.record_gap("We need a banana classifier", explicit=False)
    second = library.record_gap("We need a banana classifier", explicit=False)
    third = library.record_gap("We need a grape classifier", explicit=False)

    assert first.gap_key == second.gap_key
    assert second.frequency == 2
    assert third.gap_key != second.gap_key


def test_explicit_request_bypasses_threshold_and_creates_draft(tmp_path) -> None:
    library = build_library(tmp_path)

    document, proposal = library.propose_skill(
        "Create a skill for banana intake handling",
        target_loadout_ids=["operator_core"],
        explicit=True,
    )

    assert document.status == "draft"
    assert proposal.status == "pending_approval"
    assert Path(document.body_path).exists() or document.body_path.endswith(".md")


def test_approval_attaches_skill_to_loadout(tmp_path) -> None:
    library = build_library(tmp_path)
    document, _ = library.propose_skill(
        "Create a skill for banana intake handling",
        target_loadout_ids=["operator_core"],
        explicit=True,
    )

    approved = library.approve_skill(document.skill_id)

    assert approved.status == "approved"
    loadout = next(item for item in library.catalog_manager.list_objects("loadouts") if item.loadout_id == "operator_core")
    assert approved.body_path in loadout.skill_refs


def test_rejection_does_not_attach_skill(tmp_path) -> None:
    library = build_library(tmp_path)
    document, _ = library.propose_skill(
        "Create a skill for banana intake handling",
        target_loadout_ids=["operator_core"],
        explicit=True,
    )

    rejected = library.reject_skill(document.skill_id)

    assert rejected.status == "rejected"
    loadout = next(item for item in library.catalog_manager.list_objects("loadouts") if item.loadout_id == "operator_core")
    assert rejected.body_path not in loadout.skill_refs


def test_relevant_skills_prefer_attached_loadout_refs(tmp_path) -> None:
    library = build_library(tmp_path)
    attached, _ = library.propose_skill(
        "Create a skill for banana intake handling",
        target_loadout_ids=["operator_core"],
        explicit=True,
    )
    unattached, _ = library.propose_skill(
        "Create a skill for banana intake handling advanced",
        target_loadout_ids=["review_core"],
        explicit=True,
    )
    library.approve_skill(attached.skill_id)
    library.approve_skill(unattached.skill_id, loadout_ids=[])

    relevant = library.find_relevant_skills("banana intake handling", loadout_id="operator_core", limit=2)

    assert relevant
    assert relevant[0].skill_id == attached.skill_id


def test_monthly_review_report_flags_stale_unused_and_high_impact_skills(tmp_path) -> None:
    library = build_library(tmp_path)
    stale, _ = library.propose_skill(
        "Create a skill for stale banana intake handling",
        target_loadout_ids=["operator_core"],
        explicit=True,
    )
    hot, _ = library.propose_skill(
        "Create a skill for hot banana routing",
        target_loadout_ids=["operator_core"],
        explicit=True,
    )
    library.approve_skill(stale.skill_id)
    library.approve_skill(hot.skill_id)

    docs = library.document_store.load()
    for doc in docs:
        if doc.skill_id == stale.skill_id:
            doc.last_reviewed_at = doc.created_at - timedelta(days=40)
            doc.usage_count = 0
        if doc.skill_id == hot.skill_id:
            doc.usage_count = 4
    library.document_store.save(docs)

    report = library.generate_review_report()
    recommendations = {item.skill_id: item.recommendation for item in report.items}

    assert recommendations[stale.skill_id] in {"archive", "update"}
    assert recommendations[hot.skill_id] == "improve"
