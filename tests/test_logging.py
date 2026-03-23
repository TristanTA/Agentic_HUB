from __future__ import annotations

import json

from hub.inputs.normalize import normalize_telegram_payload
from hub.main import build_runtime


def test_structured_log_contains_prompt_and_skill_metadata(repo_copy):
    runtime = build_runtime(repo_copy)
    result = runtime.process_event(normalize_telegram_payload({"text": "hello there"}))
    structured_log = (repo_copy / "logs" / "structured.log").read_text(encoding="utf-8").strip().splitlines()
    entries = [json.loads(line) for line in structured_log]
    completed = next(item for item in reversed(entries) if item["event_type"] == "hub.run_completed")
    assert completed["run_id"] == result["run_id"]
    assert completed["prompt_files"]
    assert completed["skill_files"]
