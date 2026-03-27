from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from agentic_hub.catalog.catalog_manager import CatalogManager
from agentic_hub.core.runtime_model_store import RuntimeModelStore
from agentic_hub.models.skill_document import SkillDocument
from agentic_hub.models.skill_gap_record import SkillGapRecord
from agentic_hub.models.skill_proposal import SkillProposal
from agentic_hub.models.skill_review_report import SkillReviewItem, SkillReviewReport


STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "how",
    "i",
    "it",
    "make",
    "me",
    "my",
    "need",
    "new",
    "please",
    "skill",
    "teach",
    "the",
    "to",
    "we",
    "you",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SkillAcquisitionService:
    def build_skill(self, request_text: str, *, skill_id: str, title: str, tags: list[str]) -> tuple[str, str, list[str]]:
        summary = f"Reusable skill for {title.lower()}."
        content = "\n".join(
            [
                f"# {title}",
                "",
                "## Summary",
                summary,
                "",
                "## Guidance",
                f"- Primary demand: {request_text}",
                "- Keep responses concise and task-focused.",
                "- Prefer deterministic steps before improvisation.",
                f"- Use domain tags: {', '.join(tags) if tags else 'general'}",
            ]
        )
        evidence = [
            f"derived-from-request:{request_text}",
            "research-mode:deterministic_stub",
        ]
        return summary, content, evidence


class SkillLibrary:
    PROPOSAL_THRESHOLD = 2

    def __init__(
        self,
        *,
        runtime_dir: Path,
        repo_root: Path,
        catalog_manager: CatalogManager,
        acquisition_service: SkillAcquisitionService | None = None,
    ) -> None:
        self.runtime_dir = runtime_dir
        self.repo_root = repo_root
        self.catalog_manager = catalog_manager
        self.skills_dir = runtime_dir / "skills"
        self.document_store = RuntimeModelStore(runtime_dir / "skill_library.json", SkillDocument)
        self.gap_store = RuntimeModelStore(runtime_dir / "skill_gaps.json", SkillGapRecord)
        self.proposal_store = RuntimeModelStore(runtime_dir / "skill_proposals.json", SkillProposal)
        self.review_store = RuntimeModelStore(runtime_dir / "skill_review_reports.json", SkillReviewReport)
        self.acquisition_service = acquisition_service or SkillAcquisitionService()

    def record_gap(self, request_text: str, *, explicit: bool = False) -> SkillGapRecord:
        gap_key = self.normalize_gap_key(request_text)
        records = self.gap_store.load()
        record = next((item for item in records if item.gap_key == gap_key), None)
        if record is None:
            record = SkillGapRecord(gap_key=gap_key)
            records.append(record)
        record.frequency += 1
        if explicit:
            record.explicit_request_count += 1
        record.examples = [*record.examples[-4:], request_text]
        record.last_seen_at = utc_now()
        record.updated_at = utc_now()
        self.gap_store.save(records)
        return record

    def should_propose(self, record: SkillGapRecord, *, explicit: bool = False) -> bool:
        if explicit:
            return True
        return record.frequency >= self.PROPOSAL_THRESHOLD

    def propose_skill(
        self,
        request_text: str,
        *,
        target_loadout_ids: list[str],
        explicit: bool = False,
    ) -> tuple[SkillDocument, SkillProposal]:
        gap_record = self.record_gap(request_text, explicit=explicit)
        gap_record.proposal_count += 1
        self._save_gap_record(gap_record)

        gap_key = gap_record.gap_key
        existing = self.find_skill_by_gap(gap_key, statuses={"draft", "approved"})
        if existing is not None:
            proposal = self._upsert_proposal(existing.skill_id, target_loadout_ids, gap_key)
            return existing, proposal

        skill_id = self._skill_id_for_gap(gap_key)
        title = self._title_from_gap(gap_key)
        tags = gap_key.split("_")
        summary, content, evidence = self.acquisition_service.build_skill(
            request_text,
            skill_id=skill_id,
            title=title,
            tags=tags,
        )
        body_path = self._write_skill_body(skill_id, content)
        document = SkillDocument(
            skill_id=skill_id,
            title=title,
            summary=summary,
            content=content,
            body_path=body_path,
            evidence_sources=evidence,
            tags=tags,
            status="draft",
            demand_count=gap_record.frequency,
            target_loadout_ids=list(dict.fromkeys(target_loadout_ids)),
            gap_key=gap_key,
        )
        documents = self.document_store.load()
        documents.append(document)
        self.document_store.save(documents)

        proposal = self._upsert_proposal(skill_id, target_loadout_ids, gap_key)
        return document, proposal

    def approve_skill(self, skill_id: str, *, loadout_ids: list[str] | None = None) -> SkillDocument:
        documents = self.document_store.load()
        document = self._require_document(skill_id, documents)
        document.status = "approved"
        if loadout_ids is not None:
            document.target_loadout_ids = list(dict.fromkeys(loadout_ids))
        document.updated_at = utc_now()
        self.document_store.save(documents)
        for loadout_id in document.target_loadout_ids:
            self.attach_skill_to_loadout(skill_id, loadout_id)
        self._update_proposal_status(skill_id, "approved")
        return document

    def reject_skill(self, skill_id: str) -> SkillDocument:
        documents = self.document_store.load()
        document = self._require_document(skill_id, documents)
        document.status = "rejected"
        document.updated_at = utc_now()
        self.document_store.save(documents)
        self._update_proposal_status(skill_id, "rejected")
        return document

    def attach_skill_to_loadout(self, skill_id: str, loadout_id: str) -> None:
        document = self.get_skill(skill_id)
        loadout = next(item for item in self.catalog_manager.list_objects("loadouts") if item.loadout_id == loadout_id)
        ref = document.body_path
        if ref in loadout.skill_refs:
            return
        updated_refs = [*loadout.skill_refs, ref]
        self.catalog_manager.update("loadouts", loadout_id, {"skill_refs": updated_refs})

    def list_skills(self, *, statuses: set[str] | None = None) -> list[SkillDocument]:
        skills = self.document_store.load()
        if statuses is None:
            return skills
        return [skill for skill in skills if skill.status in statuses]

    def get_skill(self, skill_id: str) -> SkillDocument:
        documents = self.document_store.load()
        return self._require_document(skill_id, documents)

    def find_relevant_skills(self, query: str, *, loadout_id: str | None = None, limit: int = 3) -> list[SkillDocument]:
        query_tokens = set(self._tokens(query))
        results: list[tuple[int, SkillDocument]] = []
        attached_refs: set[str] = set()
        if loadout_id is not None:
            loadout = next((item for item in self.catalog_manager.list_objects("loadouts") if item.loadout_id == loadout_id), None)
            if loadout is not None:
                attached_refs = set(loadout.skill_refs)

        for skill in self.list_skills(statuses={"approved"}):
            haystack = set(self._tokens(" ".join([skill.title, skill.summary, skill.content, *skill.tags])))
            overlap = len(query_tokens & haystack)
            if overlap == 0 and skill.body_path not in attached_refs:
                continue
            score = overlap * 10
            if skill.body_path in attached_refs:
                score += 100
            results.append((score, skill))

        ordered = [skill for _, skill in sorted(results, key=lambda item: item[0], reverse=True)[:limit]]
        for skill in ordered:
            self.record_usage(skill.skill_id)
        return ordered

    def record_usage(self, skill_id: str) -> None:
        documents = self.document_store.load()
        document = self._require_document(skill_id, documents)
        document.usage_count += 1
        document.updated_at = utc_now()
        self.document_store.save(documents)

    def generate_review_report(self) -> SkillReviewReport:
        items: list[SkillReviewItem] = []
        now = utc_now()
        for skill in self.list_skills():
            if skill.status in {"rejected"}:
                continue
            age = now - (skill.last_reviewed_at or skill.created_at)
            if skill.status == "archived":
                continue
            if skill.usage_count == 0 and age > timedelta(days=30):
                items.append(SkillReviewItem(skill_id=skill.skill_id, recommendation="archive", reason="No usage in the last review window."))
            elif age > timedelta(days=30):
                items.append(SkillReviewItem(skill_id=skill.skill_id, recommendation="update", reason="Skill has not been reviewed in over 30 days."))
            elif skill.usage_count >= 3:
                items.append(SkillReviewItem(skill_id=skill.skill_id, recommendation="improve", reason="Skill is high-impact and worth improving."))
            else:
                items.append(SkillReviewItem(skill_id=skill.skill_id, recommendation="keep", reason="Skill is current and stable."))
        report = SkillReviewReport(report_id=str(uuid4()), items=items)
        reports = self.review_store.load()
        reports.append(report)
        self.review_store.save(reports)
        return report

    def find_skill_by_gap(self, gap_key: str, *, statuses: set[str]) -> SkillDocument | None:
        return next((item for item in self.document_store.load() if item.gap_key == gap_key and item.status in statuses), None)

    def get_pending_proposal(self, skill_id: str) -> SkillProposal | None:
        return next((item for item in self.proposal_store.load() if item.skill_id == skill_id and item.status == "pending_approval"), None)

    def normalize_gap_key(self, text: str) -> str:
        tokens = [token for token in self._tokens(text) if token not in STOP_WORDS]
        if not tokens:
            return "general_capability_gap"
        return "_".join(tokens[:6])

    def _skill_id_for_gap(self, gap_key: str) -> str:
        return f"skill_{gap_key}"

    def _title_from_gap(self, gap_key: str) -> str:
        return " ".join(part.capitalize() for part in gap_key.split("_"))

    def _write_skill_body(self, skill_id: str, content: str) -> str:
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        path = self.skills_dir / f"{skill_id}.md"
        path.write_text(content, encoding="utf-8")
        try:
            return path.relative_to(self.repo_root).as_posix()
        except ValueError:
            return str(path.resolve())

    def _upsert_proposal(self, skill_id: str, loadout_ids: list[str], gap_key: str) -> SkillProposal:
        proposals = self.proposal_store.load()
        proposal = next((item for item in proposals if item.skill_id == skill_id and item.status == "pending_approval"), None)
        if proposal is None:
            proposal = SkillProposal(
                proposal_id=str(uuid4()),
                skill_id=skill_id,
                approval_summary=self._approval_summary(skill_id),
                target_loadout_ids=list(dict.fromkeys(loadout_ids)),
                gap_key=gap_key,
            )
            proposals.append(proposal)
        else:
            proposal.target_loadout_ids = list(dict.fromkeys([*proposal.target_loadout_ids, *loadout_ids]))
            proposal.approval_summary = self._approval_summary(skill_id)
            proposal.updated_at = utc_now()
        self.proposal_store.save(proposals)
        return proposal

    def _approval_summary(self, skill_id: str) -> str:
        document = self.get_skill(skill_id) if any(item.skill_id == skill_id for item in self.document_store.load()) else None
        if document is None:
            return f"Approve draft skill `{skill_id}`."
        tags = ", ".join(document.tags[:4]) if document.tags else "general"
        return f"{document.title}: {document.summary} Tags: {tags}."

    def _save_gap_record(self, gap_record: SkillGapRecord) -> None:
        records = self.gap_store.load()
        updated = [item for item in records if item.gap_key != gap_record.gap_key]
        updated.append(gap_record)
        self.gap_store.save(updated)

    def _update_proposal_status(self, skill_id: str, status: str) -> None:
        proposals = self.proposal_store.load()
        for proposal in proposals:
            if proposal.skill_id == skill_id and proposal.status == "pending_approval":
                proposal.status = status
                proposal.updated_at = utc_now()
        self.proposal_store.save(proposals)

    def _require_document(self, skill_id: str, documents: list[SkillDocument]) -> SkillDocument:
        document = next((item for item in documents if item.skill_id == skill_id), None)
        if document is None:
            raise KeyError(f"Unknown skill_id: {skill_id}")
        return document

    def _tokens(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())
