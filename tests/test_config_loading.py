from __future__ import annotations

from hub.registry.loader import load_registries


def test_load_registries(repo_copy):
    bundle = load_registries(repo_copy)
    assert "vanta_manager" in bundle.agents
    assert "planning_checklist" in bundle.skills
    assert bundle.hub_config.hub.default_agent == "vanta_manager"
