from pathlib import Path

HEARTBEAT_SECONDS = 5

RUNTIME_DIR = Path("runtime")
CATALOG_SEED_DIR = Path("hub") / "catalog"
CATALOG_RUNTIME_DIR = RUNTIME_DIR / "catalog"
LOG_FILE = RUNTIME_DIR / "hub.log"
STATE_FILE = RUNTIME_DIR / "state.json"
TASKS_FILE = RUNTIME_DIR / "tasks.json"
DEAD_TASKS_FILE = RUNTIME_DIR / "dead_tasks.json"
