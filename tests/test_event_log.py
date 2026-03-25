from hub.event_log import EventLog
from schemas.event import HubEvent


def test_event_log_appends_and_filters():
    log = EventLog()
    log.append(HubEvent(event_id="e1", task_id="t1", worker_id="aria", event_type="task_started"))
    log.append(HubEvent(event_id="e2", task_id="t2", worker_id="aria", event_type="task_completed"))

    assert len(log.list_all()) == 2
    assert len(log.list_for_task("t1")) == 1
