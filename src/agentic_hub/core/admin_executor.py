from __future__ import annotations

from typing import Any

from agentic_hub.models.admin_action import AdminAction, AdminActionResult, AdminExecutionResult


class AdminExecutor:
    def __init__(self, hub: Any) -> None:
        self.hub = hub

    def execute(self, actions: list[AdminAction]) -> AdminExecutionResult:
        if not actions:
            return AdminExecutionResult(status="failed", summary="No admin actions were generated.")

        approval_actions = [action for action in actions if action.requires_approval]
        if approval_actions:
            results = [
                AdminActionResult(
                    kind=action.kind,
                    status="approval_required",
                    summary=action.summary or str(action.params.get("request_summary", "Approval required.")),
                )
                for action in approval_actions
            ]
            summary = "\n".join(
                [
                    "Approval required before changing executable code or hard-coded behavior.",
                    *[f"- {result.summary}" for result in results],
                ]
            )
            return AdminExecutionResult(status="approval_required", summary=summary, action_results=results)

        action_results: list[AdminActionResult] = []
        try:
            for action in actions:
                action_results.append(self._execute_action(action))
        except Exception as exc:
            action_results.append(
                AdminActionResult(
                    kind=action.kind,
                    status="failed",
                    summary=f"{action.kind} failed",
                    error=str(exc),
                )
            )
            return AdminExecutionResult(status="failed", summary=f"Admin action failed: {exc}", action_results=action_results)

        summary_lines = [result.summary for result in action_results]
        return AdminExecutionResult(
            status="completed",
            summary="\n".join(summary_lines),
            action_results=action_results,
        )

    def _execute_action(self, action: AdminAction) -> AdminActionResult:
        handlers = {
            "create_worker": self._create_worker,
            "update_worker": self._update_worker,
            "create_loadout": self._create_loadout,
            "create_tool": self._create_tool,
            "inspect_worker_tools": self._inspect_worker_tools,
            "inspect_worker_context": self._inspect_worker_context,
            "inspect_worker_delegation": self._inspect_worker_delegation,
            "grant_tool_access": self._grant_tool_access,
            "attach_managed_bot": self._attach_managed_bot,
            "propose_skill": self._propose_skill,
            "approve_skill": self._approve_skill,
            "reject_skill": self._reject_skill,
            "attach_skill_to_loadout": self._attach_skill_to_loadout,
            "list_skills": self._list_skills,
            "review_skills": self._review_skills,
            "start_bot": self._start_bot,
            "stop_bot": self._stop_bot,
            "run_smoke_test": self._run_smoke_test,
            "inspect_status": self._inspect_status,
            "list_objects": self._list_objects,
            "list_services": self._list_services,
        }
        return handlers[action.kind](action)

    def _create_worker(self, action: AdminAction) -> AdminActionResult:
        params = dict(action.params)
        worker_id = str(params["worker_id"])
        self.hub.catalog_manager.upsert(
            "workers",
            {
                "worker_id": worker_id,
                "name": params["name"],
                "type_id": params["type_id"],
                "role_id": params["role_id"],
                "loadout_id": params["loadout_id"],
                "interface_mode": params["interface_mode"],
                "enabled": bool(params.get("enabled", True)),
                "owner": params.get("owner"),
                "notes": params.get("notes", ""),
                "tags": list(params.get("tags", [])),
                "assigned_queues": list(params.get("assigned_queues", ["default"])),
            },
            source="runtime",
        )
        validation_results = self._validate_worker_ready(worker_id)
        if params["interface_mode"] == "managed" and params.get("bot_token"):
            attach_result = self._attach_managed_bot(
                AdminAction(
                    kind="attach_managed_bot",
                    params={"worker_id": worker_id, "bot_token": params["bot_token"]},
                    summary=f"Attach Telegram bot for {worker_id}",
                )
            )
            validation_results.extend(attach_result.validation_results)
        if params.get("smoke_test", True):
            smoke_result = self._run_smoke_test(
                AdminAction(
                    kind="run_smoke_test",
                    params={"worker_id": worker_id},
                    summary=f"Smoke test {worker_id}",
                )
            )
            validation_results.extend(smoke_result.validation_results)
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=f"Created worker `{worker_id}` and validated its runtime configuration.",
            changed_ids=[worker_id],
            validation_results=validation_results,
        )

    def _update_worker(self, action: AdminAction) -> AdminActionResult:
        worker_id = str(action.params["worker_id"])
        updates = dict(action.params["updates"])
        self.hub.catalog_manager.update("workers", worker_id, updates)
        validation_results = self._validate_worker_ready(worker_id)
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=f"Updated worker `{worker_id}`.",
            changed_ids=[worker_id],
            validation_results=validation_results,
        )

    def _create_loadout(self, action: AdminAction) -> AdminActionResult:
        params = dict(action.params)
        loadout_id = str(params["loadout_id"])
        self.hub.catalog_manager.upsert(
            "loadouts",
            {
                "loadout_id": loadout_id,
                "name": params["name"],
                "description": params.get("description", ""),
                "memory_policy_ref": params.get("memory_policy_ref", "core_memory"),
                "allowed_tool_ids": list(params.get("allowed_tool_ids", [])),
                "tool_policy_overrides": dict(params.get("tool_policy_overrides", {})),
                "tags": list(params.get("tags", [])),
            },
            source="runtime",
        )
        self.hub.worker_registry.get_loadout(loadout_id)
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=f"Created loadout `{loadout_id}`.",
            changed_ids=[loadout_id],
            validation_results=[f"loadout `{loadout_id}` is available in the active registry"],
        )

    def _create_tool(self, action: AdminAction) -> AdminActionResult:
        params = dict(action.params)
        tool_id = str(params["tool_id"])
        self.hub.catalog_manager.upsert(
            "tools",
            {
                "tool_id": tool_id,
                "name": params["name"],
                "description": params["description"],
                "implementation_ref": params["implementation_ref"],
                "capability_tags": list(params.get("capability_tags", [])),
                "safety_level": params.get("safety_level", "low"),
                "input_schema_ref": params.get("input_schema_ref"),
                "output_schema_ref": params.get("output_schema_ref"),
                "enabled": bool(params.get("enabled", True)),
            },
            source="runtime",
        )
        self.hub.tool_registry.get(tool_id)
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=f"Created tool `{tool_id}`.",
            changed_ids=[tool_id],
            validation_results=[f"tool `{tool_id}` is available in the active registry"],
        )

    def _inspect_worker_tools(self, action: AdminAction) -> AdminActionResult:
        worker_id = str(action.params["worker_id"])
        detail_level = str(action.params.get("detail_level", "concise"))
        worker = self.hub.worker_registry.get_worker(worker_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        tool_ids = list(loadout.allowed_tool_ids)
        if detail_level == "technical":
            rows = ", ".join(f"`{tool_id}`" for tool_id in tool_ids) if tool_ids else "no allowed tools"
            summary = (
                f"Worker `{worker.worker_id}` uses loadout `{loadout.loadout_id}`. "
                f"Allowed tools: {rows}."
            )
        else:
            if tool_ids:
                rows = ", ".join(f"`{tool_id}`" for tool_id in tool_ids)
                summary = f"`{worker.worker_id}` can currently use {rows}."
            else:
                summary = f"`{worker.worker_id}` does not currently have any allowed tools."
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=summary,
            changed_ids=[worker.worker_id, loadout.loadout_id, *tool_ids],
            validation_results=[f"loadout `{loadout.loadout_id}` inspected"],
        )

    def _inspect_worker_context(self, action: AdminAction) -> AdminActionResult:
        worker_id = str(action.params["worker_id"])
        detail_level = str(action.params.get("detail_level", "concise"))
        worker = self.hub.worker_registry.get_worker(worker_id)
        role = self.hub.worker_registry.get_role(worker.role_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        prompt_count = len(loadout.prompt_refs)
        skill_count = len(loadout.skill_refs)
        tool_count = len(loadout.allowed_tool_ids)
        if detail_level == "technical":
            summary = (
                f"Worker `{worker.worker_id}` | role=`{role.role_id}` | loadout=`{loadout.loadout_id}` | "
                f"interface=`{worker.interface_mode}` | prompts={prompt_count} | skills={skill_count} | tools={tool_count}"
            )
        else:
            summary = (
                f"`{worker.worker_id}` is set up as {role.name.lower()} with {tool_count} tool"
                f"{'' if tool_count == 1 else 's'}, {skill_count} skill"
                f"{'' if skill_count == 1 else 's'}, and {prompt_count} prompt context file"
                f"{'' if prompt_count == 1 else 's'}."
            )
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=summary,
            changed_ids=[worker.worker_id, loadout.loadout_id, role.role_id],
        )

    def _inspect_worker_delegation(self, action: AdminAction) -> AdminActionResult:
        preferred_ids = [worker.worker_id for worker in self.hub.worker_registry.list_workers() if worker.worker_id in {"forge", "nova"}]
        candidate_ids = preferred_ids or [worker.worker_id for worker in self.hub.worker_registry.list_workers() if worker.worker_id != "vanta"]
        if candidate_ids:
            summary = "Vanta can lean on these workers for support: " + ", ".join(f"`{worker_id}`" for worker_id in candidate_ids) + "."
        else:
            summary = "No additional workers are currently available for Vanta to delegate to."
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=summary,
            changed_ids=candidate_ids,
        )

    def _grant_tool_access(self, action: AdminAction) -> AdminActionResult:
        worker_id = str(action.params["worker_id"])
        tool_id = str(action.params["tool_id"])
        worker = self.hub.worker_registry.get_worker(worker_id)
        loadout = self.hub.worker_registry.get_loadout(worker.loadout_id)
        allowed_tool_ids = list(loadout.allowed_tool_ids)
        if tool_id not in allowed_tool_ids:
            allowed_tool_ids.append(tool_id)
        self.hub.catalog_manager.update("loadouts", loadout.loadout_id, {"allowed_tool_ids": allowed_tool_ids})
        self.hub.worker_registry.get_loadout(loadout.loadout_id)
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=f"Granted `{worker_id}` access to tool `{tool_id}` through loadout `{loadout.loadout_id}`.",
            changed_ids=[worker_id, loadout.loadout_id, tool_id],
            validation_results=[
                f"tool `{tool_id}` is allowed in loadout `{loadout.loadout_id}`",
                f"worker `{worker_id}` can now use tool `{tool_id}`",
            ],
        )

    def _attach_managed_bot(self, action: AdminAction) -> AdminActionResult:
        worker_id = str(action.params["worker_id"])
        bot_token = str(action.params["bot_token"])
        record = self.hub.telegram_runtime_manager.attach_managed_bot(worker_id, bot_token)
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=f"Attached managed Telegram bot `@{record.bot_username}` to `{worker_id}`.",
            changed_ids=[worker_id],
            validation_results=[f"managed bot `{record.bot_username}` is registered"],
        )

    def _propose_skill(self, action: AdminAction) -> AdminActionResult:
        document, proposal = self.hub.skill_library.propose_skill(
            str(action.params["request_text"]),
            target_loadout_ids=list(action.params["target_loadout_ids"]),
            explicit=bool(action.params.get("explicit", False)),
        )
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=proposal.approval_summary,
            changed_ids=[document.skill_id],
            validation_results=[f"draft skill `{document.skill_id}` stored in runtime library"],
        )

    def _approve_skill(self, action: AdminAction) -> AdminActionResult:
        loadout_ids = list(action.params.get("loadout_ids", [])) or None
        document = self.hub.skill_library.approve_skill(str(action.params["skill_id"]), loadout_ids=loadout_ids)
        validation_results = [f"skill `{document.skill_id}` approved"]
        for loadout_id in document.target_loadout_ids:
            validation_results.append(f"skill attached to loadout `{loadout_id}`")
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=f"Approved skill `{document.skill_id}` and attached it to the requested loadouts.",
            changed_ids=[document.skill_id, *document.target_loadout_ids],
            validation_results=validation_results,
        )

    def _reject_skill(self, action: AdminAction) -> AdminActionResult:
        document = self.hub.skill_library.reject_skill(str(action.params["skill_id"]))
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=f"Rejected skill `{document.skill_id}`.",
            changed_ids=[document.skill_id],
            validation_results=[f"skill `{document.skill_id}` remains unattached"],
        )

    def _attach_skill_to_loadout(self, action: AdminAction) -> AdminActionResult:
        skill_id = str(action.params["skill_id"])
        loadout_id = str(action.params["loadout_id"])
        self.hub.skill_library.attach_skill_to_loadout(skill_id, loadout_id)
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=f"Attached skill `{skill_id}` to loadout `{loadout_id}`.",
            changed_ids=[skill_id, loadout_id],
            validation_results=[f"loadout `{loadout_id}` now references skill `{skill_id}`"],
        )

    def _list_skills(self, action: AdminAction) -> AdminActionResult:
        statuses = set(action.params.get("statuses", [])) or None
        skills = self.hub.skill_library.list_skills(statuses=statuses)
        rows = [f"{skill.skill_id} | {skill.status} | usage={skill.usage_count}" for skill in skills]
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary="\n".join(rows) if rows else "No skills found.",
        )

    def _review_skills(self, action: AdminAction) -> AdminActionResult:
        report = self.hub.skill_library.generate_review_report()
        rows = [f"{item.skill_id} | {item.recommendation} | {item.reason}" for item in report.items]
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary="\n".join(rows) if rows else "No skills require review actions.",
            changed_ids=[report.report_id],
        )

    def _start_bot(self, action: AdminAction) -> AdminActionResult:
        worker_id = str(action.params["worker_id"])
        result = self.hub.telegram_runtime_manager.start_managed_bot(worker_id)
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=str(result.get("message", f"Started bot for {worker_id}")),
            changed_ids=[worker_id],
        )

    def _stop_bot(self, action: AdminAction) -> AdminActionResult:
        worker_id = str(action.params["worker_id"])
        result = self.hub.telegram_runtime_manager.stop_managed_bot(worker_id)
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=str(result.get("message", f"Stopped bot for {worker_id}")),
            changed_ids=[worker_id],
        )

    def _run_smoke_test(self, action: AdminAction) -> AdminActionResult:
        worker_id = str(action.params["worker_id"])
        validation_results = self._validate_worker_ready(worker_id)
        worker = self.hub.worker_registry.get_worker(worker_id)
        if worker.interface_mode == "managed":
            self.hub.telegram_runtime_manager.inspect_managed_bot(worker_id)
            validation_results.append(f"managed bot inspection succeeded for `{worker_id}`")
        return AdminActionResult(
            kind=action.kind,
            status="completed",
            summary=f"Smoke test passed for `{worker_id}`.",
            changed_ids=[worker_id],
            validation_results=validation_results,
        )

    def _inspect_status(self, action: AdminAction) -> AdminActionResult:
        target = str(action.params["target"]).strip()
        lowered = target.lower()
        if lowered == "hub":
            summary = (
                f"Hub `{self.hub.state.status}` | "
                f"workers={len(self.hub.worker_registry.list_workers())} | "
                f"tasks={len(self.hub.tasks)}"
            )
        elif lowered in self.hub.service_manager._services:
            status = self.hub.service_manager.status(lowered)
            summary = f"Service `{lowered}` is `{status['state']}`."
        else:
            worker = self.hub.worker_registry.get_worker(target)
            summary = (
                f"Worker `{worker.worker_id}` | type={worker.type_id} | role={worker.role_id} | "
                f"loadout={worker.loadout_id} | interface={worker.interface_mode} | enabled={worker.enabled}"
            )
        return AdminActionResult(kind=action.kind, status="completed", summary=summary)

    def _list_objects(self, action: AdminAction) -> AdminActionResult:
        kind = str(action.params["kind"])
        if kind == "tasks":
            rows = [f"{task.name} ({task.id})" for task in self.hub.tasks]
        else:
            rows = []
            for item in self.hub.catalog_manager.list_objects(kind):
                if kind == "workers":
                    rows.append(f"{item.worker_id} ({item.interface_mode})")
                elif kind == "loadouts":
                    rows.append(item.loadout_id)
                elif kind == "tools":
                    rows.append(item.tool_id)
                elif kind == "worker_roles":
                    rows.append(item.role_id)
                elif kind == "worker_types":
                    rows.append(item.type_id)
        summary = "\n".join(rows[:20]) if rows else f"No {kind} found."
        return AdminActionResult(kind=action.kind, status="completed", summary=summary)

    def _list_services(self, action: AdminAction) -> AdminActionResult:
        rows = []
        for service_name in sorted(self.hub.service_manager._services):
            status = self.hub.service_manager.status(service_name)
            rows.append(f"{service_name} | {status['state']}")
        summary = "\n".join(rows) if rows else "No services found."
        return AdminActionResult(kind=action.kind, status="completed", summary=summary)

    def _validate_worker_ready(self, worker_id: str) -> list[str]:
        worker = self.hub.worker_registry.get_worker(worker_id)
        self.hub.worker_registry.validate_worker_refs(worker_id)
        results = [
            f"worker `{worker.worker_id}` is loaded in the active registry",
            f"loadout `{worker.loadout_id}` is valid",
            f"role `{worker.role_id}` is valid",
            f"type `{worker.type_id}` is valid",
        ]
        return results
