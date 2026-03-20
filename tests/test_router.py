from __future__ import annotations

from hub.inputs.normalize import normalize_telegram_payload
from hub.registry.loader import load_registries
from hub.router.router import DeterministicRouter


def test_router_matches_planner_keywords(repo_copy):
    bundle = load_registries(repo_copy)
    router = DeterministicRouter(bundle.routes)
    decision = router.route(normalize_telegram_payload({"text": "Please plan a roadmap for this repo"}))
    assert decision.target_id == "planner_agent"


def test_router_uses_fallback(repo_copy):
    bundle = load_registries(repo_copy)
    router = DeterministicRouter(bundle.routes)
    decision = router.route(normalize_telegram_payload({"text": "hello there"}))
    assert decision.target_id == "vanta_manager"
