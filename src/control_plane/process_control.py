from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path


class ProcessController:
    def __init__(self, root_dir: Path, pid_path: Path, state_path: Path) -> None:
        self.root_dir = root_dir
        self.pid_path = pid_path
        self.state_path = state_path

    def _read_pid(self) -> int | None:
        if not self.pid_path.exists():
            return None
        try:
            return int(self.pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            return None

    def _is_process_alive(self, pid: int | None) -> bool:
        if pid is None:
            return False
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout.strip()
            return bool(output and "No tasks are running" not in output and output != "INFO: No tasks are running which match the specified criteria.")
        try:
            os.kill(pid, 0)
            return True
        except (OSError, SystemError):
            return False

    def status(self) -> dict:
        pid = self._read_pid()
        state = {}
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"pid": pid, "running": self._is_process_alive(pid), "state": state}

    def pause(self) -> dict:
        self.state_path.write_text(json.dumps({"status": "paused"}), encoding="utf-8")
        return self.status()

    def resume(self) -> dict:
        self.state_path.write_text(json.dumps({"status": "running"}), encoding="utf-8")
        return self.status()

    def start(self) -> dict:
        if self.status()["running"]:
            return self.status()
        env = os.environ.copy()
        existing_path = env.get("PYTHONPATH", "")
        src_path = str(self.root_dir / "src")
        env["PYTHONPATH"] = src_path if not existing_path else f"{src_path}{os.pathsep}{existing_path}"
        process = subprocess.Popen(
            [sys.executable, "-m", "hub.main"],
            cwd=self.root_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self.pid_path.write_text(str(process.pid), encoding="utf-8")
        self.state_path.write_text(json.dumps({"status": "running"}), encoding="utf-8")
        return self.status()

    def stop(self) -> dict:
        pid = self._read_pid()
        if pid and self._is_process_alive(pid):
            os.kill(pid, signal.SIGTERM)
        self.state_path.write_text(json.dumps({"status": "stopped"}), encoding="utf-8")
        return self.status()

    def restart(self) -> dict:
        self.stop()
        return self.start()
