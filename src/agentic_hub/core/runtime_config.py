from pathlib import Path

HEARTBEAT_SECONDS = 5

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTENT_PACKS_DIR = PROJECT_ROOT / "content" / "packs"
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
CATALOG_OVERRIDE_DIR = RUNTIME_DIR / "catalog_overrides"
CATALOG_SEED_DIR = CONTENT_PACKS_DIR
CATALOG_RUNTIME_DIR = CATALOG_OVERRIDE_DIR
LOG_FILE = RUNTIME_DIR / "hub.log"
STATE_FILE = RUNTIME_DIR / "state.json"
TASKS_FILE = RUNTIME_DIR / "tasks.json"
DEAD_TASKS_FILE = RUNTIME_DIR / "dead_tasks.json"
