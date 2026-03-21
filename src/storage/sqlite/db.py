from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from shared.schemas import AgentTaskRecord, ManagementAction, RunTrace


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
                """
            )

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
