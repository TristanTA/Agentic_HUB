from agentic_hub.core.artifact_store import ArtifactStore
from agentic_hub.models.artifact import Artifact


def test_artifact_store_saves_and_lists():
    store = ArtifactStore()
    artifact = Artifact(
        artifact_id="a1",
        task_id="t1",
        worker_id="aria",
        kind="report",
        title="Task Report",
        content={"summary": "ok"},
    )
    store.save(artifact)

    assert store.get("a1").title == "Task Report"
    assert len(store.list_for_task("t1")) == 1

