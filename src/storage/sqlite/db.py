from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.schemas import AgentTaskRecord, ManagementAction, MemoryItem, MemorySearchResult, RunTrace, ThreadWorkingState, VantaChangeRecord, VantaIncident, VantaLesson, VantaReviewCycle


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    route_json TEXT NOT NULL,
                    prompt_files_json TEXT NOT NULL,
                    skill_files_json TEXT NOT NULL,
                    markdown_handoffs_json TEXT NOT NULL,
                    outputs_json TEXT NOT NULL,
                    errors_json TEXT NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS management_audit (
                    audit_id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    result TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS health_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS telegram_sessions (
                    session_key TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS agent_tasks (
                    task_id TEXT PRIMARY KEY,
                    created_by TEXT NOT NULL,
                    assigned_to TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    input_context TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_summary TEXT NOT NULL,
                    result_payload_json TEXT NOT NULL,
                    error TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    adapter_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS vanta_reviews (
                    review_id TEXT PRIMARY KEY,
                    trigger TEXT NOT NULL,
                    focus_area TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'medium',
                    summary TEXT NOT NULL,
                    findings_json TEXT NOT NULL,
                    actions_taken_json TEXT NOT NULL,
                    open_concerns_json TEXT NOT NULL,
                    lessons_recorded_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vanta_lessons (
                    lesson_id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    situation TEXT NOT NULL,
                    action_taken TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    mistake TEXT NOT NULL,
                    updated_rule TEXT NOT NULL,
                    related_review_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vanta_changes (
                    change_id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_path TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'medium',
                    reason TEXT NOT NULL,
                    previous_content TEXT NOT NULL,
                    new_content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    rolled_back_at TEXT,
                    evaluated_at TEXT,
                    evaluation_note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS memory_items (
                    memory_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    thread_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS thread_working_state (
                    state_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    missing_information_json TEXT NOT NULL,
                    resolved_information_json TEXT NOT NULL,
                    next_step TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS vanta_incidents (
                    incident_id TEXT PRIMARY KEY,
                    component TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    likely_cause TEXT NOT NULL,
                    failure_type TEXT NOT NULL,
                    affected_agent TEXT NOT NULL,
                    last_action TEXT NOT NULL,
                    vanta_state TEXT NOT NULL,
                    next_steps_json TEXT NOT NULL,
                    thread_id TEXT,
                    run_id TEXT,
                    change_id TEXT,
                    details_json TEXT NOT NULL,
                    resolved_at TEXT,
                    resolution_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "vanta_reviews", "severity", "TEXT NOT NULL DEFAULT 'medium'")
            self._ensure_column(conn, "vanta_changes", "severity", "TEXT NOT NULL DEFAULT 'medium'")
            self._ensure_column(conn, "vanta_changes", "evaluated_at", "TEXT")
            self._ensure_column(conn, "vanta_changes", "evaluation_note", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "vanta_incidents", "resolved_at", "TEXT")
            self._ensure_column(conn, "vanta_incidents", "resolution_note", "TEXT NOT NULL DEFAULT ''")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def write_run_trace(self, trace: RunTrace) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, route_json, prompt_files_json, skill_files_json,
                    markdown_handoffs_json, outputs_json, errors_json, latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.run_id,
                    trace.route.model_dump_json(),
                    json.dumps(trace.prompt_files),
                    json.dumps(trace.skill_files),
                    json.dumps(trace.markdown_handoffs),
                    json.dumps(trace.outputs),
                    json.dumps(trace.errors),
                    trace.latency_ms,
                    trace.created_at.isoformat(),
                ),
            )

    def get_run_trace(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT run_id, route_json, outputs_json, errors_json, latency_ms, created_at FROM runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "run_id": row[0],
            "route": json.loads(row[1]),
            "outputs": json.loads(row[2]),
            "errors": json.loads(row[3]),
            "latency_ms": row[4],
            "created_at": row[5],
        }

    def recent_errors(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, errors_json, created_at
                FROM runs
                WHERE errors_json != '[]'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{"run_id": row[0], "errors": json.loads(row[1]), "created_at": row[2]} for row in rows]

    def write_management_action(self, action: ManagementAction) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO management_audit (
                    audit_id, actor, action, target, params_json, result, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.audit_id,
                    action.actor,
                    action.action,
                    action.target,
                    json.dumps(action.params),
                    action.result,
                    action.timestamp.isoformat(),
                ),
            )

    def write_health_snapshot(self, status: str, details: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO health_snapshots (status, details_json) VALUES (?, ?)",
                (status, json.dumps(details)),
            )

    def latest_health(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, details_json, created_at FROM health_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return {"status": row[0], "details": json.loads(row[1]), "created_at": row[2]}

    def upsert_telegram_session(self, session_key: str, state: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO telegram_sessions (session_key, state_json, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_key) DO UPDATE
                SET state_json = excluded.state_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_key, json.dumps(state)),
            )

    def get_telegram_session(self, session_key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json FROM telegram_sessions WHERE session_key = ?",
                (session_key,),
            ).fetchone()
        if not row:
            return None
        return json.loads(row[0])

    def delete_telegram_session(self, session_key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM telegram_sessions WHERE session_key = ?", (session_key,))

    def upsert_agent_task(self, task: AgentTaskRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_tasks (
                    task_id, created_by, assigned_to, goal, input_context, status,
                    result_summary, result_payload_json, error, artifacts_json, adapter_type,
                    created_at, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    created_by = excluded.created_by,
                    assigned_to = excluded.assigned_to,
                    goal = excluded.goal,
                    input_context = excluded.input_context,
                    status = excluded.status,
                    result_summary = excluded.result_summary,
                    result_payload_json = excluded.result_payload_json,
                    error = excluded.error,
                    artifacts_json = excluded.artifacts_json,
                    adapter_type = excluded.adapter_type,
                    created_at = excluded.created_at,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at
                """,
                (
                    task.task_id,
                    task.created_by,
                    task.assigned_to,
                    task.goal,
                    task.input_context,
                    task.status.value,
                    task.result_summary,
                    json.dumps(task.result_payload),
                    task.error,
                    json.dumps(task.artifacts),
                    task.adapter_type,
                    task.created_at.isoformat(),
                    task.started_at.isoformat() if task.started_at else None,
                    task.completed_at.isoformat() if task.completed_at else None,
                ),
            )

    def get_agent_task(self, task_id: str) -> AgentTaskRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT task_id, created_by, assigned_to, goal, input_context, status,
                       result_summary, result_payload_json, error, artifacts_json,
                       adapter_type, created_at, started_at, completed_at
                FROM agent_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_agent_task(row)

    def list_agent_tasks(
        self,
        *,
        assigned_to: str | None = None,
        created_by: str | None = None,
        limit: int = 20,
    ) -> list[AgentTaskRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if assigned_to:
            clauses.append("assigned_to = ?")
            params.append(assigned_to)
        if created_by:
            clauses.append("created_by = ?")
            params.append(created_by)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT task_id, created_by, assigned_to, goal, input_context, status,
                       result_summary, result_payload_json, error, artifacts_json,
                       adapter_type, created_at, started_at, completed_at
                FROM agent_tasks
                {where_sql}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [self._row_to_agent_task(row) for row in rows]

    def _row_to_agent_task(self, row) -> AgentTaskRecord:
        return AgentTaskRecord(
            task_id=row[0],
            created_by=row[1],
            assigned_to=row[2],
            goal=row[3],
            input_context=row[4],
            status=row[5],
            result_summary=row[6],
            result_payload=json.loads(row[7]),
            error=row[8],
            artifacts=json.loads(row[9]),
            adapter_type=row[10],
            created_at=row[11],
            started_at=row[12],
            completed_at=row[13],
        )

    def record_vanta_review(self, review: VantaReviewCycle) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO vanta_reviews (
                    review_id, trigger, focus_area, severity, summary, findings_json,
                    actions_taken_json, open_concerns_json, lessons_recorded_json,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review.review_id,
                    review.trigger,
                    review.focus_area,
                    review.severity,
                    review.summary,
                    json.dumps(review.findings),
                    json.dumps(review.actions_taken),
                    json.dumps(review.open_concerns),
                    json.dumps(review.lessons_recorded),
                    review.status,
                    review.created_at.isoformat(),
                ),
            )

    def list_vanta_reviews(self, limit: int = 10) -> list[VantaReviewCycle]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT review_id, trigger, focus_area, severity, summary, findings_json,
                       actions_taken_json, open_concerns_json, lessons_recorded_json,
                       status, created_at
                FROM vanta_reviews
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            VantaReviewCycle(
                review_id=row[0],
                trigger=row[1],
                focus_area=row[2],
                severity=row[3],
                summary=row[4],
                findings=json.loads(row[5]),
                actions_taken=json.loads(row[6]),
                open_concerns=json.loads(row[7]),
                lessons_recorded=json.loads(row[8]),
                status=row[9],
                created_at=row[10],
            )
            for row in rows
        ]

    def latest_vanta_review(self) -> VantaReviewCycle | None:
        reviews = self.list_vanta_reviews(limit=1)
        return reviews[0] if reviews else None

    def record_vanta_lesson(self, lesson: VantaLesson) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO vanta_lessons (
                    lesson_id, category, situation, action_taken, outcome,
                    mistake, updated_rule, related_review_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson.lesson_id,
                    lesson.category,
                    lesson.situation,
                    lesson.action_taken,
                    lesson.outcome,
                    lesson.mistake,
                    lesson.updated_rule,
                    lesson.related_review_id,
                    lesson.created_at.isoformat(),
                ),
            )

    def list_vanta_lessons(self, limit: int = 10) -> list[VantaLesson]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT lesson_id, category, situation, action_taken, outcome,
                       mistake, updated_rule, related_review_id, created_at
                FROM vanta_lessons
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            VantaLesson(
                lesson_id=row[0],
                category=row[1],
                situation=row[2],
                action_taken=row[3],
                outcome=row[4],
                mistake=row[5],
                updated_rule=row[6],
                related_review_id=row[7],
                created_at=row[8],
            )
            for row in rows
        ]

    def record_vanta_change(self, change: VantaChangeRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO vanta_changes (
                    change_id, target_type, target_path, severity, reason, previous_content,
                    new_content, source, applied_at, rolled_back_at, evaluated_at, evaluation_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    change.change_id,
                    change.target_type,
                    change.target_path,
                    change.severity,
                    change.reason,
                    change.previous_content,
                    change.new_content,
                    change.source,
                    change.applied_at.isoformat(),
                    change.rolled_back_at.isoformat() if change.rolled_back_at else None,
                    change.evaluated_at.isoformat() if change.evaluated_at else None,
                    change.evaluation_note,
                ),
            )

    def list_vanta_changes(self, limit: int = 10) -> list[VantaChangeRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT change_id, target_type, target_path, severity, reason, previous_content,
                       new_content, source, applied_at, rolled_back_at, evaluated_at, evaluation_note
                FROM vanta_changes
                ORDER BY applied_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            VantaChangeRecord(
                change_id=row[0],
                target_type=row[1],
                target_path=row[2],
                severity=row[3],
                reason=row[4],
                previous_content=row[5],
                new_content=row[6],
                source=row[7],
                applied_at=row[8],
                rolled_back_at=row[9],
                evaluated_at=row[10],
                evaluation_note=row[11],
            )
            for row in rows
        ]

    def get_vanta_change(self, change_id: str) -> VantaChangeRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT change_id, target_type, target_path, severity, reason, previous_content,
                       new_content, source, applied_at, rolled_back_at, evaluated_at, evaluation_note
                FROM vanta_changes
                WHERE change_id = ?
                """,
                (change_id,),
            ).fetchone()
        if not row:
            return None
        return VantaChangeRecord(
            change_id=row[0],
            target_type=row[1],
            target_path=row[2],
            severity=row[3],
            reason=row[4],
            previous_content=row[5],
            new_content=row[6],
            source=row[7],
            applied_at=row[8],
            rolled_back_at=row[9],
            evaluated_at=row[10],
            evaluation_note=row[11],
        )

    def mark_vanta_change_rolled_back(self, change_id: str, rolled_back_at: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE vanta_changes SET rolled_back_at = ? WHERE change_id = ?",
                (rolled_back_at, change_id),
            )

    def evaluate_vanta_change(self, change_id: str, evaluated_at: str, evaluation_note: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE vanta_changes SET evaluated_at = ?, evaluation_note = ? WHERE change_id = ?",
                (evaluated_at, evaluation_note, change_id),
            )

    def append_conversation_message(self, *, thread_id: str, agent_id: str, role: str, text: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_messages (thread_id, agent_id, role, text)
                VALUES (?, ?, ?, ?)
                """,
                (thread_id, agent_id, role, text),
            )

    def list_conversation_messages(self, *, thread_id: str, agent_id: str, limit: int = 12) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, text, created_at
                FROM conversation_messages
                WHERE thread_id = ? AND agent_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (thread_id, agent_id, limit),
            ).fetchall()
        return [
            {"role": row[0], "text": row[1], "created_at": row[2]}
            for row in reversed(rows)
        ]

    def upsert_memory_item(self, item: MemoryItem) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_items (
                    memory_id, scope, key, value, kind, agent_id, thread_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.memory_id,
                    item.scope,
                    item.key,
                    item.value,
                    item.kind,
                    item.agent_id,
                    item.thread_id,
                    item.created_at.isoformat(),
                ),
            )

    def list_memory_items(self, *, agent_id: str, kind: str | None = None, thread_id: str | None = None, limit: int = 20) -> list[MemoryItem]:
        clauses = ["agent_id = ?"]
        params: list[Any] = [agent_id]
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if thread_id:
            clauses.append("(thread_id = ? OR thread_id IS NULL)")
            params.append(thread_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT memory_id, scope, key, value, kind, agent_id, thread_id, created_at
                FROM memory_items
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [
            MemoryItem(
                memory_id=row[0],
                scope=row[1],
                key=row[2],
                value=row[3],
                kind=row[4],
                agent_id=row[5],
                thread_id=row[6],
                created_at=row[7],
            )
            for row in rows
        ]

    def upsert_thread_working_state(self, state: ThreadWorkingState) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO thread_working_state (
                    state_id, thread_id, agent_id, goal, missing_information_json,
                    resolved_information_json, next_step, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.state_id,
                    state.thread_id,
                    state.agent_id,
                    state.goal,
                    json.dumps(state.missing_information),
                    json.dumps(state.resolved_information),
                    state.next_step,
                    state.updated_at.isoformat(),
                ),
            )

    def get_thread_working_state(self, *, thread_id: str, agent_id: str) -> ThreadWorkingState | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT state_id, thread_id, agent_id, goal, missing_information_json,
                       resolved_information_json, next_step, updated_at
                FROM thread_working_state
                WHERE thread_id = ? AND agent_id = ?
                """,
                (thread_id, agent_id),
            ).fetchone()
        if not row:
            return None
        return ThreadWorkingState(
            state_id=row[0],
            thread_id=row[1],
            agent_id=row[2],
            goal=row[3],
            missing_information=json.loads(row[4]),
            resolved_information=json.loads(row[5]),
            next_step=row[6],
            updated_at=row[7],
        )

    def search_memory(self, *, agent_id: str, query: str, limit: int = 8) -> list[MemorySearchResult]:
        tokens = {token.lower() for token in str(query).split() if len(token.strip()) > 2}
        candidates: list[MemorySearchResult] = []
        for item in self.list_memory_items(agent_id=agent_id, limit=50):
            score = sum(1 for token in tokens if token in item.value.lower() or token in item.key.lower())
            if score:
                candidates.append(MemorySearchResult(source_type=item.kind, source_id=item.memory_id, text=item.value, score=score))
        for lesson in self.list_vanta_lessons(limit=30):
            text = f"{lesson.situation} {lesson.updated_rule} {lesson.mistake}"
            score = sum(1 for token in tokens if token in text.lower())
            if score:
                candidates.append(MemorySearchResult(source_type="lesson", source_id=lesson.lesson_id, text=lesson.updated_rule, score=score))
        for review in self.list_vanta_reviews(limit=20):
            text = f"{review.summary} {' '.join(review.findings)} {' '.join(review.open_concerns)}"
            score = sum(1 for token in tokens if token in text.lower())
            if score:
                candidates.append(MemorySearchResult(source_type="review", source_id=review.review_id, text=review.summary, score=score))
        for change in self.list_vanta_changes(limit=20):
            text = f"{change.reason} {change.target_path} {change.evaluation_note}"
            score = sum(1 for token in tokens if token in text.lower())
            if score:
                candidates.append(MemorySearchResult(source_type="change", source_id=change.change_id, text=change.reason, score=score))
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:limit]

    def record_vanta_incident(self, incident: VantaIncident) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO vanta_incidents (
                    incident_id, component, severity, summary, likely_cause, failure_type,
                    affected_agent, last_action, vanta_state, next_steps_json, thread_id,
                    run_id, change_id, details_json, resolved_at, resolution_note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident.incident_id,
                    incident.component,
                    incident.severity,
                    incident.summary,
                    incident.likely_cause,
                    incident.failure_type,
                    incident.affected_agent,
                    incident.last_action,
                    incident.vanta_state,
                    json.dumps(incident.next_steps),
                    incident.thread_id,
                    incident.run_id,
                    incident.change_id,
                    json.dumps(incident.details),
                    incident.resolved_at.isoformat() if incident.resolved_at else None,
                    incident.resolution_note,
                    incident.created_at.isoformat(),
                ),
            )

    def list_vanta_incidents(self, limit: int = 10) -> list[VantaIncident]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT incident_id, component, severity, summary, likely_cause, failure_type,
                       affected_agent, last_action, vanta_state, next_steps_json, thread_id,
                       run_id, change_id, details_json, resolved_at, resolution_note, created_at
                FROM vanta_incidents
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            VantaIncident(
                incident_id=row[0],
                component=row[1],
                severity=row[2],
                summary=row[3],
                likely_cause=row[4],
                failure_type=row[5],
                affected_agent=row[6],
                last_action=row[7],
                vanta_state=row[8],
                next_steps=json.loads(row[9]),
                thread_id=row[10],
                run_id=row[11],
                change_id=row[12],
                details=json.loads(row[13]),
                resolved_at=row[14],
                resolution_note=row[15],
                created_at=row[16],
            )
            for row in rows
        ]

    def latest_vanta_incident(self) -> VantaIncident | None:
        incidents = self.list_vanta_incidents(limit=1)
        return incidents[0] if incidents else None

    def list_active_vanta_incidents(self, limit: int = 10) -> list[VantaIncident]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT incident_id, component, severity, summary, likely_cause, failure_type,
                       affected_agent, last_action, vanta_state, next_steps_json, thread_id,
                       run_id, change_id, details_json, resolved_at, resolution_note, created_at
                FROM vanta_incidents
                WHERE resolved_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            VantaIncident(
                incident_id=row[0],
                component=row[1],
                severity=row[2],
                summary=row[3],
                likely_cause=row[4],
                failure_type=row[5],
                affected_agent=row[6],
                last_action=row[7],
                vanta_state=row[8],
                next_steps=json.loads(row[9]),
                thread_id=row[10],
                run_id=row[11],
                change_id=row[12],
                details=json.loads(row[13]),
                resolved_at=row[14],
                resolution_note=row[15],
                created_at=row[16],
            )
            for row in rows
        ]

    def latest_active_vanta_incident(self) -> VantaIncident | None:
        incidents = self.list_active_vanta_incidents(limit=1)
        return incidents[0] if incidents else None

    def resolve_vanta_incidents(self, *, component: str | None = None, failure_type: str | None = None, last_action: str | None = None, resolution_note: str = "") -> int:
        clauses = ["resolved_at IS NULL"]
        params: list[Any] = []
        if component:
            clauses.append("component = ?")
            params.append(component)
        if failure_type:
            clauses.append("failure_type = ?")
            params.append(failure_type)
        if last_action:
            clauses.append("last_action = ?")
            params.append(last_action)
        resolved_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                UPDATE vanta_incidents
                SET resolved_at = ?, resolution_note = ?
                WHERE {' AND '.join(clauses)}
                """,
                (resolved_at, resolution_note, *params),
            )
        return cursor.rowcount
