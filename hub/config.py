from pathlib import Path

HEARTBEAT_SECONDS = 5

RUNTIME_DIR = Path("runtime")
LOG_FILE = RUNTIME_DIR / "hub.log"
STATE_FILE = RUNTIME_DIR / "state.json"
TASKS_FILE = RUNTIME_DIR / "tasks.json"
DEAD_TASKS_FILE = RUNTIME_DIR / "dead_tasks.json"
