from __future__ import annotations

import os
from pathlib import Path

from control_plane.service import ControlPlaneService
from hub.registry.loader import load_registries
from hub.runtime.service import HubRuntime
from hub.telegram_runner import build_runners, run_all_runners
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
    control_plane = ControlPlaneService(runtime.root_dir)
    control_plane.bind_runtime(runtime)
    runners = build_runners(runtime, control_plane)
    run_all_runners(runners)


if __name__ == "__main__":
    main()
