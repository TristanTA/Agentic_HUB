import json
from pathlib import Path

from agentic_hub.core.hub_state import HubState


def test_hub_state_saves_to_json(tmp_path):
    state_file = tmp_path / "state.json"

    state = HubState(
        status="running",
        run_id="abc123",
        stop_requested=False,
        last_error=None,
    )
    state.save(state_file)

    assert state_file.exists()

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["status"] == "running"
    assert data["run_id"] == "abc123"
    assert data["stop_requested"] is False
    assert data["last_error"] is None

