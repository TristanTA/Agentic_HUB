from __future__ import annotations

import json

from hub.inputs.normalize import normalize_telegram_payload
from hub.main import build_runtime


def test_structured_log_contains_prompt_and_skill_metadata(repo_copy):
    runtime = build_runtime(repo_copy)
    result = runtime.process_event(normalize_telegram_payload({"text": "hello there"}))
    structured_log = (repo_copy / "logs" / "structured.log").read_text(encoding="utf-8").strip().splitlines()
    latest = json.loads(structured_log[-1])
    assert latest["event_type"] == "hub.run_completed"
    assert latest["run_id"] == result["run_id"]
    assert latest["prompt_files"]
    assert latest["skill_files"]
