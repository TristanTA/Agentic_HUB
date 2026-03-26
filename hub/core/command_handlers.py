from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hub.runtime_status import build_runtime_status


class CommandHandlers:
    def __init__(self, hub: Any) -> None:
        self.hub = hub

    def handle(self, command: str, payload: dict[str, Any]) -> str:
        command = command.strip()
        normalized = command.split(maxsplit=1)[0].lower() if command else ""

        if normalized == "/ping":
            return "hub alive"

        if normalized == "/status":
            return self._status()

        if normalized == "/tasks":
            return self._tasks()

        if normalized == "/services":
            return self._services()

        if normalized == "/help":
            return self._help()

        if normalized == "/runtime":
            return self._runtime()

        if normalized == "/catalog":
            return self._catalog(command)

        return f"unknown command: {normalized or command}"

    def _status(self) -> str:
        now = datetime.now(timezone.utc)

        queued = 0
        running = 0
        done = 0
        failed = 0

        startup_pending = 0
        interval_enabled = 0
        due = 0
        success = 0
        never_run = 0

        for t in self.hub.tasks:
            # Old HubTask shape used in tests
            if hasattr(t, "status"):
                status = getattr(t, "status", None)
                if status == "queued":
                    queued += 1
                elif status == "running":
                    running += 1
                elif status == "done":
                    done += 1
                elif status == "failed":
                    failed += 1
                continue

            # Real Task shape used by hub runtime
            enabled = getattr(t, "enabled", True)
            if not enabled:
                continue

            trigger = getattr(t, "trigger", None)
            last_status = getattr(t, "last_status", None)
            next_run_at = getattr(t, "next_run_at", None)
            task_id = getattr(t, "id", None)

            if trigger == "startup" and task_id not in getattr(self.hub, "ran_startup_ids", set()):
                startup_pending += 1

            if trigger == "interval":
                interval_enabled += 1
                if next_run_at is not None and now >= next_run_at:
                    due += 1

            if last_status == "failed":
                failed += 1
            elif last_status == "success":
                success += 1
            elif last_status is None:
                never_run += 1

        # Preserve old test expectations if HubTask-style objects are present
        if queued or running or done or failed:
            return (
                "hub status\n"
                f"- queued: {queued}\n"
                f"- running: {running}\n"
                f"- done: {done}\n"
                f"- failed: {failed}"
            )

        return (
            "hub status\n"
            f"- state: {getattr(self.hub.state, 'status', 'unknown')}\n"
            f"- startup pending: {startup_pending}\n"
            f"- interval enabled: {interval_enabled}\n"
            f"- due now: {due}\n"
            f"- last success: {success}\n"
            f"- last failed: {failed}\n"
            f"- never run: {never_run}"
        )

    def _tasks(self) -> str:
        if not self.hub.tasks:
            return "no tasks"

        recent = self.hub.tasks[-10:]
        lines = ["recent tasks:"]

        for t in recent:
            # Old HubTask shape used in tests
            if hasattr(t, "task_id"):
                lines.append(
                    f"- {t.task_id} | {t.kind} | {t.status}"
                )
                continue

            # Real Task shape
            lines.append(
                f"- {getattr(t, 'id', '?')} | {getattr(t, 'name', '?')} | "
                f"trigger={getattr(t, 'trigger', '?')} | "
                f"enabled={getattr(t, 'enabled', '?')} | "
                f"last_status={getattr(t, 'last_status', None)}"
            )

        return "\n".join(lines)

    def _services(self) -> str:
        rows = self.hub.service_manager.list_status()
        if not rows:
            return "no services registered"

        lines = ["services:"]
        for row in rows:
            lines.append(f"- {row['name']} | {row['state']}")
        return "\n".join(lines)

    def _help(self) -> str:
        return "\n".join([
            "commands:",
            "/ping",
            "/status",
            "/tasks",
            "/services",
            "/runtime",
            "/catalog ...",
            "/help",
        ])

    def _runtime(self) -> str:
        return build_runtime_status(
            self.hub.event_log,
            self.hub.artifact_store,
            self.hub.approval_manager,
            self.hub.catalog_manager,
        )

    def _catalog(self, command: str) -> str:
        parts = command.split(maxsplit=3)
        if len(parts) == 1:
            return self._catalog_help()

        action = parts[1]
        if action == "list":
            if len(parts) < 3:
                return "usage: /catalog list <tools|worker_types|worker_roles|loadouts|memory_policies|workers>"
            kind = parts[2]
            items = self.hub.catalog_manager.list_objects(kind)
            if not items:
                return f"no {kind}"
            lines = [f"{kind}:"]
            for item in items:
                identifier = self._catalog_identifier(kind, item)
                lines.append(f"- {identifier} | source={getattr(item, 'source', 'runtime')}")
            return "\n".join(lines)

        if action == "create":
            if len(parts) < 4:
                return "usage: /catalog create <kind> <json>"
            kind = parts[2]
            payload = json.loads(parts[3])
            object_id = self.hub.catalog_manager.upsert(kind, payload)
            return f"created {kind} {object_id}"

        if action == "update":
            if len(parts) < 4:
                return "usage: /catalog update <kind> <id> <json>"
            extra = parts[3].split(maxsplit=1)
            if len(extra) != 2:
                return "usage: /catalog update <kind> <id> <json>"
            kind = parts[2]
            object_id, raw_updates = extra
            updates = json.loads(raw_updates)
            self.hub.catalog_manager.update(kind, object_id, updates)
            return f"updated {kind} {object_id}"

        if action in {"enable", "disable"}:
            if len(parts) < 4:
                return "usage: /catalog enable|disable <tools|workers> <id>"
            kind = parts[2]
            object_id = parts[3]
            self.hub.catalog_manager.set_enabled(kind, object_id, action == "enable")
            return f"{action}d {kind} {object_id}"

        if action == "assign":
            if len(parts) < 4:
                return "usage: /catalog assign worker <worker_id> <type|role|loadout> <value>"
            extra = parts[3].split()
            if parts[2] != "worker" or len(extra) != 3:
                return "usage: /catalog assign worker <worker_id> <type|role|loadout> <value>"
            worker_id, target, value = extra
            mapping = {"type": "type_id", "role": "role_id", "loadout": "loadout_id"}
            self.hub.catalog_manager.assign_worker(worker_id, mapping[target], value)
            return f"assigned worker {worker_id} {target}={value}"

        if action == "import":
            if len(parts) < 3:
                return "usage: /catalog import <path> [--override]"
            arg_parts = command.split()[2:]
            allow_override = "--override" in arg_parts
            path = Path(next(part for part in arg_parts if part != "--override"))
            counts = self.hub.catalog_manager.import_package(path, allow_override=allow_override)
            summary = ", ".join(f"{kind}={count}" for kind, count in counts.items() if count)
            return f"imported package from {path}: {summary or 'no objects'}"

        if action == "export":
            if len(parts) < 3:
                return "usage: /catalog export <path>"
            path = Path(command.split(maxsplit=2)[2])
            exported = self.hub.catalog_manager.export_package(path)
            return f"exported package to {exported}"

        return self._catalog_help()

    def _catalog_help(self) -> str:
        return "\n".join(
            [
                "catalog commands:",
                "/catalog list <kind>",
                "/catalog create <kind> <json>",
                "/catalog update <kind> <id> <json>",
                "/catalog enable <tools|workers> <id>",
                "/catalog disable <tools|workers> <id>",
                "/catalog assign worker <worker_id> <type|role|loadout> <value>",
                "/catalog import <path> [--override]",
                "/catalog export <path>",
            ]
        )

    def _catalog_identifier(self, kind: str, item: Any) -> str:
        fields = {
            "tools": "tool_id",
            "worker_types": "type_id",
            "worker_roles": "role_id",
            "loadouts": "loadout_id",
            "memory_policies": "policy_id",
            "workers": "worker_id",
        }
        return str(getattr(item, fields[kind]))
