from __future__ import annotations

import os
from pathlib import Path

from hub.inputs.normalize import normalize_telegram_payload
from hub.registry.loader import load_registries
from hub.runtime.service import HubRuntime
from shared.settings import AppSettings


def build_runtime(root_dir: str | Path | None = None) -> HubRuntime:
    settings = AppSettings.load(root_dir)
    settings.ensure_directories()
    bundle = load_registries(settings.root_dir)
    runtime = HubRuntime(settings.root_dir, bundle)
    runtime.pid_path.write_text(str(os.getpid()), encoding="utf-8")
    return runtime


def main() -> None:
    runtime = build_runtime()
    runtime.process_event(normalize_telegram_payload({"text": "hello from local bootstrap", "thread_id": "bootstrap"}))


if __name__ == "__main__":
    main()
