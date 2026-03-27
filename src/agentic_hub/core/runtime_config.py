from pathlib import Path

HEARTBEAT_SECONDS = 5

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CONTENT_PACKS_DIR = PROJECT_ROOT / "content" / "packs"
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
CATALOG_OVERRIDE_DIR = RUNTIME_DIR / "catalog_overrides"
CATALOG_SEED_DIR = CONTENT_PACKS_DIR
CATALOG_RUNTIME_DIR = CATALOG_OVERRIDE_DIR
ENV_FILE = PROJECT_ROOT / ".env"
MANAGED_TELEGRAM_BOTS_FILE = RUNTIME_DIR / "managed_telegram_bots.json"
TELEGRAM_CONVERSATIONS_FILE = RUNTIME_DIR / "telegram_conversation_sessions.json"
APPROVALS_FILE = RUNTIME_DIR / "approvals.json"
ARTIFACTS_FILE = RUNTIME_DIR / "artifacts.json"
EVENTS_FILE = RUNTIME_DIR / "events.json"
LIVE_WORKFLOWS_FILE = RUNTIME_DIR / "live_workflows.json"
LIVE_WORKFLOW_TASKS_FILE = RUNTIME_DIR / "live_workflow_tasks.json"
LOG_FILE = RUNTIME_DIR / "hub.log"
STATE_FILE = RUNTIME_DIR / "state.json"
TASKS_FILE = RUNTIME_DIR / "tasks.json"
DEAD_TASKS_FILE = RUNTIME_DIR / "dead_tasks.json"
