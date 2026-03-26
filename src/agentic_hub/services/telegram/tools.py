from __future__ import annotations

from typing import Any


def start_telegram_service(hub: Any) -> dict:
    return hub.service_manager.start("telegram")


def stop_telegram_service(hub: Any) -> dict:
    return hub.service_manager.stop("telegram")


def telegram_service_status(hub: Any) -> dict:
    return hub.service_manager.status("telegram")