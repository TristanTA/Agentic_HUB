from __future__ import annotations

from typing import Any, Dict, List, Optional

from schemas.memory_records import RunEpisode, SemanticFact, SessionEpisode


class MemoryManager:
    """
    Minimal first-pass memory service.

    - working memory: in-process dict
    - episodic memory: in-memory episode/session stores
    - semantic memory: in-memory fact store

    Replace the episodic/semantic layers with SQLite or another persistent store later.
    """

    def __init__(self) -> None:
        self._working_memory: Dict[str, Dict[str, Any]] = {}
        self._run_episodes: Dict[str, RunEpisode] = {}
        self._session_episodes: Dict[str, SessionEpisode] = {}
        self._semantic_facts: Dict[str, List[SemanticFact]] = {}

    # Working memory

    def start_run(self, run_id: str, initial_context: Optional[Dict[str, Any]] = None) -> None:
        self._working_memory[run_id] = dict(initial_context or {})

    def get_working_memory(self, run_id: str) -> Dict[str, Any]:
        return dict(self._working_memory.get(run_id, {}))

    def update_working_memory(self, run_id: str, updates: Dict[str, Any]) -> None:
        self._working_memory.setdefault(run_id, {}).update(updates)

    def end_run(self, run_id: str) -> Dict[str, Any]:
        return self._working_memory.pop(run_id, {})

    # Episodic memory

    def save_run_episode(self, episode: RunEpisode) -> None:
        self._run_episodes[episode.run_id] = episode

    def get_run_episode(self, run_id: str) -> Optional[RunEpisode]:
        return self._run_episodes.get(run_id)

    def save_session_episode(self, episode: SessionEpisode) -> None:
        self._session_episodes[episode.session_id] = episode

    def get_session_episode(self, session_id: str) -> Optional[SessionEpisode]:
        return self._session_episodes.get(session_id)

    # Semantic memory

    def upsert_semantic_fact(self, fact: SemanticFact) -> None:
        bucket = self._semantic_facts.setdefault(fact.key, [])
        active_idx = None
        for idx, existing in enumerate(bucket):
            if existing.status == "active":
                active_idx = idx
                break

        if active_idx is not None:
            old = bucket[active_idx].model_copy()
            old.status = "superseded"
            bucket[active_idx] = old

        bucket.append(fact)

    def get_active_semantic_fact(self, key: str) -> Optional[SemanticFact]:
        facts = self._semantic_facts.get(key, [])
        for fact in reversed(facts):
            if fact.status == "active":
                return fact
        return None

    def get_semantic_history(self, key: str) -> List[SemanticFact]:
        return list(self._semantic_facts.get(key, []))

    # Context assembly

    def build_context_bundle(
        self,
        run_id: str,
        session_id: Optional[str] = None,
        semantic_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        semantic = {}
        for key in semantic_keys or []:
            fact = self.get_active_semantic_fact(key)
            if fact is not None:
                semantic[key] = fact.value

        return {
            "working_memory": self.get_working_memory(run_id),
            "session_episode": self.get_session_episode(session_id) if session_id else None,
            "semantic_memory": semantic,
        }
