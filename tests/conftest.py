import sys
import logging
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(autouse=True)
def clear_live_telegram_env(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.setattr(
        "agentic_hub.core.telegram_runtime_manager.TelegramRuntimeManager.register_persisted_managed_bots",
        lambda self: None,
    )


@pytest.fixture(autouse=True)
def isolate_hub_logger():
    logger = logging.getLogger("hub")
    original_handlers = list(logger.handlers)
    original_level = logger.level
    original_propagate = logger.propagate

    for handler in original_handlers:
        logger.removeHandler(handler)

    null_handler = logging.NullHandler()
    logger.addHandler(null_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        yield
    finally:
        logger.removeHandler(null_handler)
        for handler in original_handlers:
            logger.addHandler(handler)
        logger.setLevel(original_level)
        logger.propagate = original_propagate
