from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentic_hub.core.command_spec import CHOICE_SOURCES, CREATE_FIELDS, EDITABLE_FIELDS, FIELD_HINTS, KIND_LABELS, OBJECT_KINDS
from agentic_hub.core.command_state import CommandSession
from agentic_hub.core.runtime_status import build_runtime_status
from agentic_hub.core.legacy_tasks import Task, utc_now


class CommandHandlers:
    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self._sessions: dict[str, CommandSession] = {}

    def handle(self, command: str, payload: dict[str, Any]) -> str:
        command = command.strip()
        session_key = self._session_key(payload)
        if session_key in self._sessions and (not command.startswith("/") or command.lower() in {"confirm", "cancel", "back"}):
            return self._handle_session_input(session_key, command)

        normalized = command.split(maxsplit=1)[0].lower() if command else ""
        if normalized == "/ping":
            return self._render("Hub alive", [], ["/status", "/workers", "/help"])
        if normalized == "/help":
            return self._help()
        if normalized == "/status":
            return self._status()
        if normalized == "/inspect":
            return self._inspect(command)
        if normalized == "/workers":
            return self._catalog_list("workers")
        if normalized == "/tools":
            return self._catalog_list("tools")
        if normalized == "/loadouts":
            return self._catalog_list("loadouts")
        if normalized == "/roles":
            return self._catalog_list("worker_roles")
        if normalized == "/types":
            return self._catalog_list("worker_types")
        if normalized == "/tasks":
            return self._tasks()
        if normalized == "/logs":
            return self._logs()
        if normalized == "/new":
            return self._start_session(session_key, "new")
        if normalized == "/edit":
            return self._start_session(session_key, "edit")
        if normalized == "/delete":
            return self._start_session(session_key, "delete")
        if normalized == "/pause":
            return self._pause(command)
        if normalized == "/resume":
            return self._resume(command)
        if normalized == "/retry":
            return self._retry(command)
        if normalized == "/services":
            return self._services()
        if normalized == "/runtime":
            return self._runtime()
        if normalized == "/telegram":
            return self._telegram(command)
        if normalized == "/chat-open":
            return self._chat_open(command, payload)
        if normalized == "/chat-close":
            return self._chat_close(command, payload)
        if normalized == "/chat":
            return self._chat(command, payload)
        if normalized == "/chat-sessions":
            return self._chat_sessions(payload)
        if normalized == "/catalog":
            return self._catalog(command)
        return self._render(f"Unknown command: {normalized or command}", ["Command not recognized."], ["/help", "/status", "/inspect"])

    def _session_key(self, payload: dict[str, Any]) -> str:
        return f"{payload.get('source', 'local')}:{payload.get('chat_id', 'default')}:{payload.get('user_id', 'anon')}"

    def _start_session(self, session_key: str, mode: str) -> str:
        self._sessions[session_key] = CommandSession(mode=mode, step="kind")
        rows = [f"[{idx}] {KIND_LABELS[kind]} | {kind}" for idx, kind in enumerate(OBJECT_KINDS, start=1)]
        return self._render(f"{mode.title()} wizard", ["Choose object type:", *rows], ["reply with number or kind", "cancel"])

    def _handle_session_input(self, session_key: str, command: str) -> str:
        session = self._sessions[session_key]
        lowered = command.strip().lower()
        if lowered == "cancel":
            del self._sessions[session_key]
            return self._render("Wizard cancelled", [], ["/help", "/new"])
        if lowered == "back":
            session.step = "kind"
            session.kind = None
            session.object_id = None
            session.draft.clear()
            return self._start_session(session_key, session.mode)

        if session.step == "kind":
            kind = self._resolve_kind(command)
            if not kind:
                return self._render("Invalid target", ["Reply with a valid object type or list number."], ["reply again", "cancel"])
            session.kind = kind
            session.step = "object" if session.mode in {"edit", "delete"} else "field"
            if session.mode == "new":
                session.metadata["field_index"] = 0
                return self._prompt_field(session)
            rows = self._list_rows(kind)
            return self._render(f"Select {KIND_LABELS[kind]}", rows or ["No objects available."], ["reply with number or id", "back", "cancel"])

        if session.step == "object":
            object_id = self._resolve_object_id(session.kind or "", command)
            if not object_id:
                return self._render("Unknown object", ["Reply with a list number or object id."], ["reply again", "back", "cancel"])
            session.object_id = object_id
            session.step = "confirm" if session.mode == "delete" else "field"
            if session.mode == "delete":
                deps = self._dependency_lines(session.kind or "", object_id)
                return self._render(f"Delete {KIND_LABELS[session.kind or 'object']}", [f"Target: {object_id}", *deps], ["confirm", "back", "cancel"])
            return self._prompt_edit_field(session)

        if session.step == "field":
            return self._handle_field_input(session, command)

        if session.step == "value":
            return self._handle_value_input(session, command)

        if session.step == "confirm":
            if lowered != "confirm":
                return self._render("Confirmation required", ["Reply with `confirm` to continue."], ["confirm", "back", "cancel"])
            result = self._commit_session(session)
            del self._sessions[session_key]
            return result

        del self._sessions[session_key]
        return self._render("Wizard reset", ["Session state was invalid and has been cleared."], ["/help"])

    def _handle_field_input(self, session: CommandSession, command: str) -> str:
        if session.mode == "new":
            fields = CREATE_FIELDS[session.kind or ""]
            index = int(session.metadata.get("field_index", 0))
            field_name = fields[index]
            try:
                session.draft[field_name] = self._parse_user_value(field_name, command)
            except ValueError as exc:
                return self._render(f"Invalid value for {field_name}", [str(exc)], ["reply again", "back", "cancel"])

            index += 1
            session.metadata["field_index"] = index
            if index >= len(fields):
                session.step = "confirm"
                preview = [f"{key}: {value}" for key, value in session.draft.items()]
                return self._render("Preview changes", preview, ["confirm", "back", "cancel"])
            return self._prompt_field(session)

        if session.mode == "edit":
            field_name = command.strip()
            if field_name not in EDITABLE_FIELDS[session.kind or ""]:
                return self._render("Field not editable", ["Reply with one of the editable field names shown."], ["reply again", "back", "cancel"])
            session.field_name = field_name
            session.step = "value"
            return self._prompt_edit_value(session)

        return self._render("Wizard reset", ["Unsupported field step."], ["/help"])

    def _handle_value_input(self, session: CommandSession, command: str) -> str:
        field_name = session.field_name or ""
        try:
            session.draft = {field_name: self._parse_user_value(field_name, command)}
        except ValueError as exc:
            return self._render(f"Invalid value for {field_name}", [str(exc)], ["reply again", "back", "cancel"])
        session.step = "confirm"
        preview = [f"Field: {field_name}", f"New value: {session.draft[field_name]}"]
        return self._render("Preview changes", preview, ["confirm", "back", "cancel"])

    def _commit_session(self, session: CommandSession) -> str:
        kind = session.kind or ""
        if session.mode == "new":
            object_id = self._create_object(kind, session.draft)
            return self._render(f"Created {KIND_LABELS[kind]}", [f"Object id: {object_id}"], [f"/inspect {kind} {object_id}", "/edit", "/delete"])
        if session.mode == "edit":
            self._edit_object(kind, session.object_id or "", session.draft)
            return self._render(f"Updated {KIND_LABELS[kind]}", [f"Object id: {session.object_id}", f"Changed fields: {', '.join(session.draft.keys())}"], [f"/inspect {kind} {session.object_id}", "/logs"])
        if session.mode == "delete":
            self._delete_object(kind, session.object_id or "")
            return self._render(f"Delete flow complete for {KIND_LABELS[kind]}", [f"Target: {session.object_id}"], ["/logs", "/help"])
        return self._render("Wizard failed", ["Unsupported session mode."], ["/help"])

    def _help(self) -> str:
        return self._render(
            "Hub command guide",
            [
                "Commands:",
                "/help, /new, /edit, /delete",
                "/workers, /tasks, /status, /inspect, /logs",
                "/tools, /loadouts, /roles, /types",
                "/pause, /resume, /retry",
                "/telegram, /chat-open, /chat, /chat-close, /chat-sessions",
                "Common objects: workers, worker_roles, worker_types, tools, loadouts, tasks",
                "Example flow: /new -> worker -> answer prompts -> confirm",
            ],
            ["/status", "/workers", "/new"],
        )

    def _status(self) -> str:
        now = datetime.now(timezone.utc)
        failed = sum(getattr(t, "last_status", None) == "failed" or getattr(t, "status", None) == "failed" for t in self.hub.tasks)
        scheduled = sum(getattr(t, "trigger", None) in {"interval", "once"} for t in self.hub.tasks)
        overdue = sum(getattr(t, "next_run_at", None) is not None and now >= t.next_run_at for t in self.hub.tasks if getattr(t, "trigger", None) in {"interval", "once"})
        worker_registry = getattr(self.hub, "worker_registry", None)
        workers = worker_registry.list_workers() if worker_registry is not None else []
        enabled = [w for w in workers if w.enabled]
        errors = [w for w in workers if w.health != "healthy"]
        running = [w for w in workers if w.status == "running"]
        state = getattr(getattr(self.hub, "state", None), "status", "unknown")
        lines = [
            f"Hub: {state}",
            f"Workers: {len(workers)} total | {len(enabled)} enabled | {len(running)} running | {len(errors)} error",
            f"Tasks: {len(self.hub.tasks)} total | {failed} failed | {scheduled} scheduled",
            f"Scheduler: {'paused' if getattr(self.hub, 'scheduler_paused', False) else 'running'}",
            f"Overdue scheduled tasks: {overdue}",
        ]
        return self._render("Operational status", lines, ["/workers", "/tasks", "/logs"])

    def _runtime(self) -> str:
        lines = build_runtime_status(self.hub.event_log, self.hub.artifact_store, self.hub.approval_manager, self.hub.catalog_manager).splitlines()
        return self._render("Runtime status", lines[1:], ["/status", "/workers", "/tools"])

    def _services(self) -> str:
        rows = [f"[{idx}] {row['name']} | {row['state']} | service" for idx, row in enumerate(self.hub.service_manager.list_status(), start=1)]
        return self._render("Services", rows or ["No services registered."], ["/status", "/help"])

    def _tasks(self) -> str:
        return self._render("Tasks", [self._task_row(idx, task) for idx, task in enumerate(self.hub.tasks, start=1)] or ["No tasks available."], ["/inspect tasks <id>", "/retry <task_id>", "/delete"])

    def _logs(self) -> str:
        rows = [f"[{idx}] {event.created_at.isoformat()} | info | {event.event_type} | task={event.task_id or '-'} | worker={event.worker_id or '-'}" for idx, event in enumerate(self.hub.event_log.list_all()[-10:], start=1)]
        return self._render("Recent logs", rows or ["No recent logs."], ["/inspect tasks <id>", "/retry <task_id>", "/status"])

    def _catalog_list(self, kind: str) -> str:
        title = {"workers": "Workers", "tools": "Tools", "loadouts": "Loadouts", "worker_roles": "Roles", "worker_types": "Worker types"}[kind]
        return self._render(title, self._list_rows(kind) or ["No objects available."], [f"/inspect {kind} <id>", "/edit", "/delete"])

    def _prompt_field(self, session: CommandSession) -> str:
        fields = CREATE_FIELDS[session.kind or ""]
        index = int(session.metadata.get("field_index", 0))
        field_name = fields[index]
        body = [f"Field {index + 1} of {len(fields)}: {field_name}", self._field_hint(field_name)]
        body.extend(self._choice_lines(field_name))
        return self._render(f"Create {KIND_LABELS[session.kind or 'object']}", body, ["reply with value", "back", "cancel"])

    def _prompt_edit_field(self, session: CommandSession) -> str:
        fields = [f"- {field}" for field in EDITABLE_FIELDS[session.kind or ""]]
        deps = self._dependency_lines(session.kind or "", session.object_id or "")
        return self._render(
            f"Edit {KIND_LABELS[session.kind or 'object']}",
            [f"Target: {session.object_id}", "Editable fields:", *fields, *deps],
            ["reply with field name", "back", "cancel"],
        )

    def _prompt_edit_value(self, session: CommandSession) -> str:
        field_name = session.field_name or ""
        body = [f"Field: {field_name}", self._field_hint(field_name)]
        body.extend(self._choice_lines(field_name))
        return self._render(f"Set {field_name}", body, ["reply with value", "back", "cancel"])

    def _inspect(self, command: str) -> str:
        parts = command.split(maxsplit=2)
        if len(parts) < 3:
            return self._render("Inspect command", ["Usage: /inspect <kind> <id>"], ["/workers", "/tasks", "/tools"])
        kind = self._resolve_kind(parts[1])
        object_id = parts[2].strip()
        if not kind:
            return self._render("Unknown kind", ["Inspect target type not recognized."], ["/help"])
        data = self._inspect_data(kind, object_id)
        if not data:
            return self._render("Object not found", [f"No {kind} matched `{object_id}`."], ["/help", "/workers", "/tasks"])
        deps = self._dependency_lines(kind, data["id"])
        body = ["Summary:"] + [f"- {key}: {value}" for key, value in data.items()]
        if deps:
            body += ["Dependencies:"] + [f"- {line}" for line in deps]
        return self._render(f"Inspect {KIND_LABELS.get(kind, kind)} {data['id']}", body, ["/edit", "/delete", "/logs"])

    def _pause(self, command: str) -> str:
        parts = command.split()
        if len(parts) >= 3 and parts[1].lower() == "worker":
            self.hub.catalog_manager.update("workers", parts[2], {"status": "paused"})
            return self._render("Worker paused", [f"Worker: {parts[2]}"], ["/resume worker " + parts[2], "/workers"])
        self.hub.state.status = "paused"
        return self._render("Hub paused", ["Hub state has been set to paused."], ["/resume hub", "/status"])

    def _resume(self, command: str) -> str:
        parts = command.split()
        if len(parts) >= 3 and parts[1].lower() == "worker":
            self.hub.catalog_manager.update("workers", parts[2], {"status": "enabled"})
            return self._render("Worker resumed", [f"Worker: {parts[2]}"], ["/workers", "/inspect workers " + parts[2]])
        self.hub.state.status = "running"
        return self._render("Hub resumed", ["Hub state has been set to running."], ["/status", "/workers"])

    def _retry(self, command: str) -> str:
        parts = command.split()
        if len(parts) < 2:
            failed = [task for task in self.hub.tasks if getattr(task, "last_status", None) == "failed"]
            return self._render("Retryable tasks", [self._task_row(idx, task) for idx, task in enumerate(failed, start=1)] or ["No failed tasks available."], ["/retry <task_id>", "/tasks"])
        task = self._find_task(parts[1])
        if not task:
            return self._render("Unknown task", ["Task not found."], ["/tasks", "/logs"])
        cloned = Task(id=str(uuid.uuid4()), name=f"{task.name} (retry)", handler_name=task.handler_name, priority=task.priority, enabled=True, trigger="once", next_run_at=utc_now(), payload=dict(task.payload))
        self.hub.tasks.append(cloned)
        self.hub.task_store.save(self.hub.tasks)
        return self._render("Retry launched", [f"Original task: {parts[1]}", f"New task id: {cloned.id}"], [f"/inspect tasks {cloned.id}", "/tasks"])

    def _catalog(self, command: str) -> str:
        parts = command.split(maxsplit=3)
        try:
            if len(parts) == 1:
                return self._render("Catalog commands", ["/catalog list <kind>", "/catalog create <kind> <json>", "/catalog update <kind> <id> <json>", "/catalog enable <tools|workers> <id>", "/catalog disable <tools|workers> <id>", "/catalog assign worker <worker_id> <type|role|loadout> <value>", "/catalog import <path> [--override]", "/catalog export <path>"], ["/help", "/new"])
            if parts[1] == "list":
                return self._render("Catalog list", self._list_rows(parts[2]), [f"/inspect {parts[2]} <id>", "/edit", "/delete"])
            if parts[1] == "create":
                object_id = self.hub.catalog_manager.upsert(parts[2], json.loads(parts[3]))
                return self._render("Catalog object created", [f"Kind: {parts[2]}", f"Object id: {object_id}"], [f"/inspect {parts[2]} {object_id}", "/edit"])
            if parts[1] == "update":
                object_id, raw_updates = parts[3].split(maxsplit=1)
                self.hub.catalog_manager.update(parts[2], object_id, json.loads(raw_updates))
                return self._render("Catalog object updated", [f"Kind: {parts[2]}", f"Object id: {object_id}"], [f"/inspect {parts[2]} {object_id}", "/logs"])
            if parts[1] in {"enable", "disable"}:
                self.hub.catalog_manager.set_enabled(parts[2], parts[3], parts[1] == "enable")
                return self._render(f"{parts[1].title()} complete", [f"Kind: {parts[2]}", f"Object id: {parts[3]}"], [f"/inspect {parts[2]} {parts[3]}", "/help"])
            if parts[1] == "assign":
                worker_id, target, value = parts[3].split()
                self.hub.catalog_manager.assign_worker(worker_id, {"type": "type_id", "role": "role_id", "loadout": "loadout_id"}[target], value)
                return self._render("Worker assignment updated", [f"Worker: {worker_id}", f"{target}: {value}"], [f"/inspect workers {worker_id}", "/workers"])
            if parts[1] == "import":
                arg_parts = command.split()[2:]
                allow_override = "--override" in arg_parts
                path = Path(next(part for part in arg_parts if part != "--override"))
                counts = self.hub.catalog_manager.import_package(path, allow_override=allow_override)
                return self._render("Package imported", [f"Path: {path}", *[f"{kind}: {count}" for kind, count in counts.items()]], ["/workers", "/tools", "/loadouts"])
            if parts[1] == "export":
                exported = self.hub.catalog_manager.export_package(Path(command.split(maxsplit=2)[2]))
                return self._render("Package exported", [f"Path: {exported}"], ["/catalog list workers", "/help"])
        except Exception as exc:
            return self._render("Catalog command failed", [str(exc)], ["/help", "/logs"])
        return self._render("Catalog command", ["Unknown catalog subcommand."], ["/help", "/catalog"])

    def _telegram(self, command: str) -> str:
        parts = command.split(maxsplit=3)
        manager = getattr(self.hub, "telegram_runtime_manager", None)
        if manager is None:
            return self._render("Telegram manager unavailable", [], ["/help"])
        try:
            if len(parts) == 1:
                return self._render(
                    "Telegram commands",
                    [
                        "/telegram bots",
                        "/telegram attachbot <worker_id> <token>",
                        "/telegram removebot <worker_id>",
                        "/telegram startbot <worker_id>",
                        "/telegram stopbot <worker_id>",
                        "/telegram inspectbot <worker_id>",
                    ],
                    ["/workers", "/services"],
                )
            if parts[1] == "bots":
                bots = manager.list_managed_bots()
                lines = [f"- {bot.worker_id} | @{bot.bot_username} | {'enabled' if bot.enabled else 'disabled'}" for bot in bots]
                return self._render("Managed Telegram bots", lines or ["No managed bots registered."], ["/telegram"])
            if parts[1] == "attachbot":
                worker_id, token = parts[2], parts[3]
                record = manager.attach_managed_bot(worker_id, token)
                return self._render(
                    "Managed bot attached",
                    [f"Worker: {worker_id}", f"Bot: @{record.bot_username}", "Bot runtime started."],
                    [f"/telegram inspectbot {worker_id}", "/services"],
                )
            if parts[1] == "removebot":
                manager.remove_managed_bot(parts[2])
                return self._render("Managed bot removed", [f"Worker: {parts[2]}"], ["/telegram bots", "/workers"])
            if parts[1] == "startbot":
                result = manager.start_managed_bot(parts[2])
                return self._render("Managed bot start", [str(result.get("message", result))], ["/services", f"/telegram inspectbot {parts[2]}"])
            if parts[1] == "stopbot":
                result = manager.stop_managed_bot(parts[2])
                return self._render("Managed bot stop", [str(result.get("message", result))], ["/services", f"/telegram inspectbot {parts[2]}"])
            if parts[1] == "inspectbot":
                data = manager.inspect_managed_bot(parts[2])
                body = [f"{key}: {value}" for key, value in data.items()]
                return self._render("Managed bot", body, ["/telegram bots", "/services"])
        except Exception as exc:
            return self._render("Telegram command failed", [str(exc)], ["/telegram", "/help"])
        return self._render("Telegram command", ["Unknown telegram subcommand."], ["/telegram", "/help"])

    def _chat_open(self, command: str, payload: dict[str, Any]) -> str:
        parts = command.split(maxsplit=1)
        if len(parts) < 2:
            return self._render("Hybrid chat", ["Usage: /chat-open <worker_id>"], ["/workers", "/help"])
        manager = getattr(self.hub, "telegram_runtime_manager", None)
        if manager is None:
            return self._render("Hybrid chat unavailable", [], ["/help"])
        try:
            session = manager.open_hybrid_session(parts[1], int(payload.get("chat_id", 0)), payload.get("user_id"))
        except Exception as exc:
            return self._render("Hybrid chat failed", [str(exc)], ["/workers", "/help"])
        return self._render(
            "Hybrid session opened",
            [f"Worker: {session.worker_id}", "Use /chat <message> to continue."],
            ["/chat <message>", "/chat-close", "/chat-sessions"],
        )

    def _chat_close(self, command: str, payload: dict[str, Any]) -> str:
        parts = command.split(maxsplit=1)
        worker_id = parts[1] if len(parts) > 1 else None
        manager = getattr(self.hub, "telegram_runtime_manager", None)
        if manager is None:
            return self._render("Hybrid chat unavailable", [], ["/help"])
        closed = manager.close_hybrid_session(int(payload.get("chat_id", 0)), worker_id)
        return self._render(
            "Hybrid sessions closed",
            [f"- {session.worker_id}" for session in closed] or ["No matching active sessions."],
            ["/chat-sessions", "/workers"],
        )

    def _chat_sessions(self, payload: dict[str, Any]) -> str:
        manager = getattr(self.hub, "telegram_runtime_manager", None)
        if manager is None:
            return self._render("Hybrid chat unavailable", [], ["/help"])
        sessions = manager.list_hybrid_sessions(int(payload.get("chat_id", 0)))
        lines = [f"- {session.worker_id} | active={session.active} | messages={len(session.messages)}" for session in sessions]
        return self._render("Hybrid sessions", lines or ["No active hybrid sessions."], ["/chat-open <worker_id>", "/workers"])

    def _chat(self, command: str, payload: dict[str, Any]) -> str:
        manager = getattr(self.hub, "telegram_runtime_manager", None)
        if manager is None:
            return self._render("Hybrid chat unavailable", [], ["/help"])
        try:
            remainder = command.split(maxsplit=1)[1]
        except IndexError:
            return self._render("Hybrid chat", ["Usage: /chat <worker_id> <message> or /chat <message> with an active session"], ["/chat-open <worker_id>", "/chat-sessions"])

        worker_id: str | None = None
        message = remainder
        parts = remainder.split(maxsplit=1)
        if len(parts) == 2:
            try:
                self.hub.worker_registry.get_worker(parts[0])
                worker_id = parts[0]
                message = parts[1]
            except Exception:
                worker_id = None

        try:
            reply = manager.send_hybrid_message(
                chat_id=int(payload.get("chat_id", 0)),
                user_id=payload.get("user_id"),
                worker_id=worker_id,
                text=message,
            )
        except Exception as exc:
            return self._render("Hybrid chat failed", [str(exc)], ["/chat-open <worker_id>", "/chat-sessions"])
        return self._render("Hybrid reply", [reply], ["/chat <message>", "/chat-close", "/chat-sessions"])

    def _resolve_kind(self, raw: str) -> str | None:
        mapping = {"worker": "workers", "workers": "workers", "role": "worker_roles", "roles": "worker_roles", "worker_roles": "worker_roles", "type": "worker_types", "types": "worker_types", "worker_types": "worker_types", "tool": "tools", "tools": "tools", "loadout": "loadouts", "loadouts": "loadouts", "task": "tasks", "tasks": "tasks"}
        value = raw.strip().lower()
        if value.isdigit():
            index = int(value) - 1
            return OBJECT_KINDS[index] if 0 <= index < len(OBJECT_KINDS) else None
        return mapping.get(value)

    def _resolve_object_id(self, kind: str, raw: str) -> str | None:
        if kind == "tasks":
            task = self._find_task(raw) if not raw.isdigit() else (self.hub.tasks[int(raw) - 1] if 0 < int(raw) <= len(self.hub.tasks) else None)
            return getattr(task, "id", None) if task else None
        items = self.hub.catalog_manager.list_objects(kind)
        if raw.isdigit():
            return self._catalog_identifier(kind, items[int(raw) - 1]) if 0 < int(raw) <= len(items) else None
        return raw if any(self._catalog_identifier(kind, item) == raw for item in items) else None

    def _list_rows(self, kind: str) -> list[str]:
        if kind == "tasks":
            return [self._task_row(idx, task) for idx, task in enumerate(self.hub.tasks, start=1)]
        rows = []
        for idx, item in enumerate(self.hub.catalog_manager.list_objects(kind), start=1):
            identifier = self._catalog_identifier(kind, item)
            name = getattr(item, "name", identifier)
            status = ("enabled" if getattr(item, "enabled", False) else "disabled") if kind in {"workers", "tools"} else getattr(item, "status", "active")
            refs = (
                f"{item.type_id}/{item.role_id}/{getattr(item, 'interface_mode', 'internal')}"
                if kind == "workers"
                else (f"tools={len(item.allowed_tool_ids)}" if kind == "loadouts" else getattr(item, "purpose", getattr(item, "execution_mode", getattr(item, "safety_level", "-"))))
            )
            rows.append(f"[{idx}] {name} | {identifier} | {status} | {refs}")
        return rows

    def _inspect_data(self, kind: str, object_id: str) -> dict[str, Any]:
        resolved_id = self._resolve_object_id(kind, object_id)
        if not resolved_id:
            return {}
        if kind == "tasks":
            task = self._find_task(resolved_id)
            if not task:
                return {}
            return {
                "id": getattr(task, "id", getattr(task, "task_id", "?")),
                "name": getattr(task, "name", getattr(task, "kind", "?")),
                "kind": getattr(task, "handler_name", getattr(task, "kind", "?")),
                "status": getattr(task, "last_status", getattr(task, "status", "queued")) or "queued",
                "created_at": getattr(task, "next_run_at", getattr(task, "created_at", None)),
                "updated_at": getattr(task, "last_run_at", None),
                "priority": getattr(task, "priority", None),
                "payload": getattr(task, "payload", {}),
                "retry_count": getattr(task, "retry_count", 0),
                "last_error": getattr(task, "last_error", getattr(task, "error", None)),
            }
        item = next(item for item in self.hub.catalog_manager.list_objects(kind) if self._catalog_identifier(kind, item) == resolved_id)
        data = item.model_dump(mode="python")
        data["id"] = resolved_id
        data["kind"] = kind
        data.setdefault("status", "enabled" if getattr(item, "enabled", False) else "active")
        return data

    def _dependency_lines(self, kind: str, object_id: str) -> list[str]:
        return [] if kind == "tasks" else self.hub.catalog_manager.dependency_summary(kind, object_id)

    def _create_object(self, kind: str, draft: dict[str, Any]) -> str:
        if kind == "tasks":
            task = Task(id=str(uuid.uuid4()), name=str(draft["name"]), handler_name=str(draft["handler_name"]), priority=int(draft["priority"]), enabled=bool(draft.get("enabled", True)), trigger=str(draft["trigger"]), interval_seconds=draft.get("interval_seconds"), next_run_at=utc_now(), payload=dict(draft.get("payload", {})))
            self.hub.tasks.append(task)
            self.hub.task_store.save(self.hub.tasks)
            return task.id
        field = {"workers": "worker_id", "worker_roles": "role_id", "worker_types": "type_id", "tools": "tool_id", "loadouts": "loadout_id"}[kind]
        payload = dict(draft)
        payload[field] = self._slugify(str(draft["name"]))
        return self.hub.catalog_manager.upsert(kind, payload)

    def _edit_object(self, kind: str, object_id: str, updates: dict[str, Any]) -> None:
        if kind == "tasks":
            task = self._find_task(object_id)
            if not task:
                raise KeyError(f"Unknown task id: {object_id}")
            for key, value in updates.items():
                setattr(task, key, value)
            self.hub.task_store.save(self.hub.tasks)
            return
        self.hub.catalog_manager.update(kind, object_id, updates)

    def _delete_object(self, kind: str, object_id: str) -> None:
        if kind == "tasks":
            self.hub.tasks = [task for task in self.hub.tasks if getattr(task, "id", getattr(task, "task_id", None)) != object_id]
            self.hub.task_store.save(self.hub.tasks)
            return
        self.hub.catalog_manager.delete(kind, object_id)

    def _find_task(self, task_id: str) -> Task | None:
        for task in self.hub.tasks:
            current_id = getattr(task, "id", getattr(task, "task_id", None))
            if current_id == task_id:
                return task
        return None

    def _task_row(self, idx: int, task: Task) -> str:
        task_id = getattr(task, "id", getattr(task, "task_id", "?"))
        name = getattr(task, "name", getattr(task, "kind", "?"))
        status = getattr(task, "last_status", getattr(task, "status", "queued")) or "queued"
        priority = getattr(task, "priority", "?")
        return f"[{idx}] {name} | {task_id} | {status} | priority={priority}"

    def _catalog_identifier(self, kind: str, item: Any) -> str:
        fields = {"tools": "tool_id", "worker_types": "type_id", "worker_roles": "role_id", "loadouts": "loadout_id", "memory_policies": "policy_id", "workers": "worker_id"}
        return str(getattr(item, fields[kind]))

    def _render(self, summary: str, body_lines: list[str], next_actions: list[str]) -> str:
        lines = [summary]
        if body_lines:
            lines.append("")
            lines.extend(body_lines)
        lines.append("")
        lines.append("Next:")
        lines.extend(f"- {action}" for action in next_actions)
        return "\n".join(lines)

    def _slugify(self, value: str) -> str:
        slug = value.strip().lower().replace(" ", "_")
        return "".join(ch for ch in slug if ch.isalnum() or ch == "_")

    def _field_hint(self, field_name: str) -> str:
        return FIELD_HINTS.get(field_name, f"Enter {field_name}.")

    def _choice_lines(self, field_name: str) -> list[str]:
        source = CHOICE_SOURCES.get(field_name)
        if source is None:
            return []
        if isinstance(source, list):
            return [f"Options: {', '.join(source)}"]
        items = self.hub.catalog_manager.list_objects(source)
        if source == "memory_policies":
            ids = [self._catalog_identifier("memory_policies", item) for item in items]
        else:
            ids = [self._catalog_identifier(source, item) for item in items]
        return [f"Options: {', '.join(ids)}"]

    def _parse_user_value(self, field_name: str, raw: str) -> Any:
        value = raw.strip()
        lowered = value.lower()
        if field_name in {"enabled", "can_use_tools", "can_spawn_tasks", "can_request_approval"}:
            if lowered in {"yes", "y", "true", "on", "enabled"}:
                return True
            if lowered in {"no", "n", "false", "off", "disabled"}:
                return False
            raise ValueError("Please answer yes or no.")
        if field_name in {"priority", "priority_bias", "interval_seconds"}:
            if value == "" and field_name == "interval_seconds":
                return None
            return int(value)
        if field_name in {"allowed_task_kinds", "allowed_tool_ids", "capability_tags", "tags"}:
            if value.startswith("["):
                parsed = json.loads(value)
                if not isinstance(parsed, list):
                    raise ValueError("Expected a list.")
                return parsed
            return [item.strip() for item in value.split(",") if item.strip()]
        if field_name in {"tool_policy_overrides", "payload"}:
            if not value:
                return {}
            return json.loads(value)
        if field_name in {"type_id", "role_id", "loadout_id", "memory_policy_ref", "safety_level", "execution_mode", "trigger"}:
            if lowered in {"none", "blank"} and field_name == "memory_policy_ref":
                return None
            return value
        return value


