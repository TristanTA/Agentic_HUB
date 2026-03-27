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
            "attach_managed_bot": self._attach_managed_bot,
            "start_bot": self._start_bot,
            "stop_bot": self._stop_bot,
            "run_smoke_test": self._run_smoke_test,
            "inspect_status": self._inspect_status,
            "list_objects": self._list_objects,
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
