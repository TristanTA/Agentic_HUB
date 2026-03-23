from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from vanta_core.process_control import RuntimeProcessController


class VantaGuardian:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.runtime = RuntimeProcessController(
            root_dir,
            root_dir / "data" / "agent_os.pid",
            root_dir / "data" / "agent_os_state.json",
        )
        self.state_path = root_dir / "data" / "vanta_core_state.json"
        self.pid_path = root_dir / "data" / "vanta_core.pid"

    def run_forever(self, sleep_seconds: float = 2.0) -> None:
        self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        child = self._start_bot()
        self.runtime.start()
        self.runtime.record_healthy_runtime()
        while True:
            runtime_status = self.runtime.status()
            if not runtime_status.get("running") and runtime_status.get("restart_allowed", True):
                self.runtime.start()
            if child.poll() is not None:
                child = self._start_bot()
            self._write_state(child.pid, runtime_status)
            time.sleep(sleep_seconds)

    def _start_bot(self) -> subprocess.Popen:
        env = os.environ.copy()
        src_path = str(self.root_dir / "src")
        env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
        return subprocess.Popen(
            [sys.executable, "-m", "vanta_core.main", "run-bot"],
            cwd=self.root_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    def _write_state(self, bot_pid: int, runtime_status: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {
                    "status": "running",
                    "bot_pid": bot_pid,
                    "runtime": runtime_status,
                    "updated_at": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
