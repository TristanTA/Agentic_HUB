from __future__ import annotations

from hub.main import build_runtime
from hub.runtime.vanta_operator import VantaOperator


def test_vanta_operator_run_once_records_review_and_lesson(repo_copy):
    runtime = build_runtime(repo_copy)
    operator = VantaOperator(runtime)

    result = operator.run_once(trigger="test")

    assert result["trigger"] == "test"
    assert runtime.store.latest_vanta_review() is not None
    assert isinstance(runtime.store.list_vanta_lessons(limit=5), list)
