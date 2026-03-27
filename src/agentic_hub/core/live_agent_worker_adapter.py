from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests

from agentic_hub.catalog.worker_registry import WorkerRegistry
from agentic_hub.core.approval_manager import ApprovalManager
from agentic_hub.core.artifact_store import ArtifactStore
from agentic_hub.core.repo_tools import RepoTools
from agentic_hub.core.web_research import WebResearchClient
from agentic_hub.core.worker_adapter import WorkerAdapter
from agentic_hub.models.approval import ApprovalRequest
from agentic_hub.models.artifact import Artifact
from agentic_hub.models.task import Task
from agentic_hub.models.task_result import TaskResult
from agentic_hub.models.worker_instance import WorkerInstance


class LiveAgentWorkerAdapter(WorkerAdapter):
    def __init__(
        self,
        *,
        worker_registry: WorkerRegistry,
        artifact_store: ArtifactStore,
        approval_manager: ApprovalManager,
        repo_root: Path,
    ) -> None:
        self.worker_registry = worker_registry
        self.artifact_store = artifact_store
        self.approval_manager = approval_manager
        self.repo_tools = RepoTools(repo_root)
        self.web_client = WebResearchClient()

    def run(self, worker: WorkerInstance, task: Task) -> TaskResult:
        if task.kind == "research_request":
            return self._run_research(worker, task)
        if task.kind == "implementation_request":
            return self._run_implementation(worker, task)
        if task.kind == "verification_request":
            return self._run_verification(worker, task)
        if task.kind == "message":
            return TaskResult(
                task_id=task.task_id,
                worker_id=worker.worker_id,
                status="done",
                summary="Message task is handled by the Telegram conversation runtime.",
            )
        return TaskResult(
            task_id=task.task_id,
            worker_id=worker.worker_id,
            status="failed",
            summary=f"Unsupported task kind for agent worker: {task.kind}",
            error="unsupported_task_kind",
        )

    def _run_research(self, worker: WorkerInstance, task: Task) -> TaskResult:
        target_worker_id = str(task.payload["target_worker_id"])
        objective = str(task.payload["objective"])
        operator_worker_id = str(task.payload["operator_worker_id"])

        context = self._build_research_context(target_worker_id, objective)
        brief = self._generate_research_brief(worker, target_worker_id, objective, context)

        artifact = Artifact(
            artifact_id=str(uuid4()),
            task_id=task.task_id,
            worker_id=worker.worker_id,
            kind="research_brief",
            title=f"Research brief for {target_worker_id}",
            content=brief,
        )
        self.artifact_store.save(artifact)

        return TaskResult(
            task_id=task.task_id,
            worker_id=worker.worker_id,
            status="done",
            summary=brief.get("summary", f"Research complete for {target_worker_id}."),
            artifact_refs=[artifact.artifact_id],
            follow_up_tasks=[
                {
                    "kind": "implementation_request",
                    "payload": {
                        "workflow_id": task.payload["workflow_id"],
                        "target_worker_id": target_worker_id,
                        "objective": objective,
                        "research_artifact_id": artifact.artifact_id,
                    },
                    "target_worker_id": operator_worker_id,
                }
            ],
        )

    def _run_implementation(self, worker: WorkerInstance, task: Task) -> TaskResult:
        research_artifact = self.artifact_store.get(str(task.payload["research_artifact_id"]))
        objective = str(task.payload["objective"])
        target_worker_id = str(task.payload["target_worker_id"])

        change_set = self._generate_change_set(worker, objective, target_worker_id, research_artifact.content)
        change_artifact = Artifact(
            artifact_id=str(uuid4()),
            task_id=task.task_id,
            worker_id=worker.worker_id,
            kind="change_set",
            title=f"Proposed repo changes for {target_worker_id}",
            content=change_set,
        )
        self.artifact_store.save(change_artifact)

        approval = ApprovalRequest(
            approval_id=str(uuid4()),
            task_id=task.task_id,
            requested_by_worker_id=worker.worker_id,
            requested_for_worker_id=worker.worker_id,
            title=f"Approve repo changes for {target_worker_id}",
            summary=self._approval_summary(change_set),
            risk_level="high",
        )
        self.approval_manager.create_request(approval)

        approval_artifact = Artifact(
            artifact_id=str(uuid4()),
            task_id=task.task_id,
            worker_id=worker.worker_id,
            kind="approval_request",
            title=approval.title,
            content={
                "approval_id": approval.approval_id,
                "summary": approval.summary,
                "risk_level": approval.risk_level,
                "change_set_artifact_id": change_artifact.artifact_id,
            },
        )
        self.artifact_store.save(approval_artifact)

        return TaskResult(
            task_id=task.task_id,
            worker_id=worker.worker_id,
            status="needs_approval",
            summary="Implementation plan prepared and waiting for approval.",
            artifact_refs=[change_artifact.artifact_id, approval_artifact.artifact_id],
            output_payload={
                "approval_id": approval.approval_id,
                "change_set_artifact_id": change_artifact.artifact_id,
            },
        )

    def _run_verification(self, worker: WorkerInstance, task: Task) -> TaskResult:
        commands = list(task.payload.get("commands", []))
        results = [self.repo_tools.run_command(command) for command in commands]
        artifact = Artifact(
            artifact_id=str(uuid4()),
            task_id=task.task_id,
            worker_id=worker.worker_id,
            kind="verification_report",
            title="Verification results",
            content={"commands": results},
        )
        self.artifact_store.save(artifact)
        failed = [result for result in results if int(result["returncode"]) != 0]
        summary = "Verification completed successfully." if not failed else "Verification found failing checks."
        return TaskResult(
            task_id=task.task_id,
            worker_id=worker.worker_id,
            status="done" if not failed else "failed",
            summary=summary,
            artifact_refs=[artifact.artifact_id],
            error=json.dumps(failed, indent=2) if failed else None,
        )

    def _build_research_context(self, target_worker_id: str, objective: str) -> dict[str, Any]:
        worker = self.worker_registry.get_worker(target_worker_id)
        role = self.worker_registry.get_role(worker.role_id)
        loadout = self.worker_registry.get_loadout(worker.loadout_id)
        worker_file = f"content/packs/basic/workers/{target_worker_id}.json"
        candidate_matches = self.repo_tools.search_files(target_worker_id, limit=12)
        read_paths = [worker_file]
        read_paths.extend(match["path"] for match in candidate_matches if match["path"] not in read_paths)

        files: list[dict[str, str]] = []
        for path in read_paths[:6]:
            try:
                files.append({"path": path, "content": self.repo_tools.read_file(str(path))[:12000]})
            except Exception:
                continue

        web_results = self.web_client.search(f"{objective} {target_worker_id} AI persona prompt markdown", max_results=4)
        fetched_pages: list[dict[str, str]] = []
        for result in web_results[:2]:
            try:
                fetched_pages.append(
                    {
                        "title": result["title"],
                        "url": result["url"],
                        "content": self.web_client.fetch_page(result["url"], max_chars=5000),
                    }
                )
            except Exception:
                continue

        return {
            "target_worker": worker.model_dump(mode="json"),
            "target_role": role.model_dump(mode="json"),
            "target_loadout": loadout.model_dump(mode="json"),
            "repo_files": files,
            "web_results": web_results,
            "web_pages": fetched_pages,
        }

    def _generate_research_brief(
        self,
        worker: WorkerInstance,
        target_worker_id: str,
        objective: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = {
            "task": "research_brief",
            "objective": objective,
            "target_worker_id": target_worker_id,
            "context": context,
            "required_output": {
                "summary": "short summary",
                "objective": objective,
                "target_workers": [target_worker_id],
                "findings": ["key findings"],
                "recommended_changes": ["specific recommendations"],
                "files_to_create": ["repo-relative paths"],
                "files_to_update": ["repo-relative paths"],
                "tools_to_add": ["tool ids or names"],
                "skills_to_add": ["skill names or file paths"],
                "verification_steps": ["commands or checks"],
                "risks": ["risks or open questions"],
            },
        }
        system_prompt = self._worker_system_prompt(worker, "You are the internal research worker. Produce a concrete implementation brief.")
        return self._json_completion(system_prompt, prompt)

    def _generate_change_set(
        self,
        worker: WorkerInstance,
        objective: str,
        target_worker_id: str,
        research_brief: dict[str, Any],
    ) -> dict[str, Any]:
        target_paths = list(dict.fromkeys([*research_brief.get("files_to_update", []), *research_brief.get("files_to_create", [])]))
        file_context: list[dict[str, str]] = []
        for path in target_paths[:6]:
            try:
                file_context.append({"path": path, "content": self.repo_tools.read_file(path)[:14000]})
            except FileNotFoundError:
                file_context.append({"path": path, "content": ""})
            except Exception:
                continue

        prompt = {
            "task": "implementation_change_set",
            "objective": objective,
            "target_worker_id": target_worker_id,
            "research_brief": research_brief,
            "file_context": file_context,
            "required_output": {
                "summary": "short summary",
                "file_operations": [
                    {
                        "path": "repo-relative path",
                        "action": "create|update|delete",
                        "reason": "why this change is needed",
                        "content": "full file contents for create/update, omit for delete",
                    }
                ],
                "verification_commands": ["powershell commands"],
                "risks": ["risks or follow-ups"],
            },
        }
        system_prompt = self._worker_system_prompt(
            worker,
            "You are the internal operator worker. Return a concrete repo change set with full file contents.",
        )
        return self._json_completion(system_prompt, prompt)

    def _approval_summary(self, change_set: dict[str, Any]) -> str:
        operations = change_set.get("file_operations", [])
        if not operations:
            return change_set.get("summary", "No file operations proposed.")
        parts = [f"{item.get('action', 'update')} {item.get('path', '?')}" for item in operations]
        return "; ".join(parts[:8])

    def _worker_system_prompt(self, worker: WorkerInstance, instruction: str) -> str:
        role = self.worker_registry.get_role(worker.role_id)
        loadout = self.worker_registry.get_loadout(worker.loadout_id)
        return "\n".join(
            [
                f"You are {worker.name} ({worker.worker_id}).",
                f"Role: {role.name} - {role.purpose}",
                f"Loadout: {loadout.name}",
                instruction,
                "Return only valid JSON.",
                "Prefer concrete file paths and implementation-ready outputs.",
            ]
        )

    def _json_completion(self, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")

        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(payload)},
                ],
            },
            timeout=90,
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            text = "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
        else:
            text = str(content)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                return json.loads(text[start : end + 1])
            raise
