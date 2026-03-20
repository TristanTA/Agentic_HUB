from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from shared.schemas import ManagementAction, RunTrace


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
