from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from agentic_hub.models.memory_records import RunEpisode, SemanticFact, SessionEpisode


class SQLiteMemoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS run_episodes (
                    run_id TEXT PRIMARY KEY,
                    worker_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    actions_summary TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS session_episodes (
                    session_id TEXT PRIMARY KEY,
                    participants_json TEXT NOT NULL,
                    goals_json TEXT NOT NULL,
                    key_events_json TEXT NOT NULL,
                    unresolved_items_json TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                '''
            )
            conn.execute(
                '''
                CREATE TABLE IF NOT EXISTS semantic_facts (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    valid_from TEXT,
                    valid_to TEXT,
                    confidence REAL NOT NULL,
                    source_episode_id TEXT,
                    last_updated TEXT NOT NULL
                )
                '''
            )

    def save_run_episode(self, episode: RunEpisode) -> None:
        with self._connect() as conn:
            conn.execute(
                '''
                INSERT OR REPLACE INTO run_episodes
                (run_id, worker_id, task_id, objective, actions_summary, outcome, artifacts_json, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    episode.run_id,
                    episode.worker_id,
                    episode.task_id,
                    episode.objective,
                    episode.actions_summary,
                    episode.outcome,
                    json.dumps(episode.artifacts),
                    episode.timestamp.isoformat(),
                ),
            )

    def get_run_episode(self, run_id: str) -> Optional[RunEpisode]:
        with self._connect() as conn:
            row = conn.execute(
                '''
                SELECT run_id, worker_id, task_id, objective, actions_summary, outcome, artifacts_json, timestamp
                FROM run_episodes WHERE run_id = ?
                ''',
                (run_id,),
            ).fetchone()

        if row is None:
            return None

        return RunEpisode(
            run_id=row[0],
            worker_id=row[1],
            task_id=row[2],
            objective=row[3],
            actions_summary=row[4],
            outcome=row[5],
            artifacts=json.loads(row[6]),
            timestamp=row[7],
        )

    def save_session_episode(self, episode: SessionEpisode) -> None:
        with self._connect() as conn:
            conn.execute(
                '''
                INSERT OR REPLACE INTO session_episodes
                (session_id, participants_json, goals_json, key_events_json, unresolved_items_json, summary, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    episode.session_id,
                    json.dumps(episode.participants),
                    json.dumps(episode.goals),
                    json.dumps(episode.key_events),
                    json.dumps(episode.unresolved_items),
                    episode.summary,
                    episode.updated_at.isoformat(),
                ),
            )

    def get_session_episode(self, session_id: str) -> Optional[SessionEpisode]:
        with self._connect() as conn:
            row = conn.execute(
                '''
                SELECT session_id, participants_json, goals_json, key_events_json, unresolved_items_json, summary, updated_at
                FROM session_episodes WHERE session_id = ?
                ''',
                (session_id,),
            ).fetchone()

        if row is None:
            return None

        return SessionEpisode(
            session_id=row[0],
            participants=json.loads(row[1]),
            goals=json.loads(row[2]),
            key_events=json.loads(row[3]),
            unresolved_items=json.loads(row[4]),
            summary=row[5],
            updated_at=row[6],
        )

    def upsert_semantic_fact(self, fact: SemanticFact) -> None:
        with self._connect() as conn:
            conn.execute(
                '''
                UPDATE semantic_facts
                SET status = 'superseded'
                WHERE fact_key = ? AND status = 'active'
                ''',
                (fact.key,),
            )
            conn.execute(
                '''
                INSERT INTO semantic_facts
                (fact_key, value_json, status, valid_from, valid_to, confidence, source_episode_id, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    fact.key,
                    json.dumps(fact.value),
                    fact.status,
                    fact.valid_from.isoformat() if fact.valid_from else None,
                    fact.valid_to.isoformat() if fact.valid_to else None,
                    fact.confidence,
                    fact.source_episode_id,
                    fact.last_updated.isoformat(),
                ),
            )

    def get_active_semantic_fact(self, key: str) -> Optional[SemanticFact]:
        with self._connect() as conn:
            row = conn.execute(
                '''
                SELECT fact_key, value_json, status, valid_from, valid_to, confidence, source_episode_id, last_updated
                FROM semantic_facts
                WHERE fact_key = ? AND status = 'active'
                ORDER BY row_id DESC
                LIMIT 1
                ''',
                (key,),
            ).fetchone()

        if row is None:
            return None

        return SemanticFact(
            key=row[0],
            value=json.loads(row[1]),
            status=row[2],
            valid_from=row[3],
            valid_to=row[4],
            confidence=row[5],
            source_episode_id=row[6],
            last_updated=row[7],
        )

