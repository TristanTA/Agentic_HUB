from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


class RuntimeProcessController:
    def __init__(self, root_dir: Path, pid_path: Path, state_path: Path) -> None:
        self.root_dir = root_dir
        self.pid_path = pid_path
        self.state_path = state_path
        self.supervision_path = root_dir / "data" / "agent_os_supervision.json"

    def status(self) -> dict:
        pid = self._read_pid()
        state = {}
        if self.state_path.exists():
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        supervision = self._read_supervision_state()
        return {
            "pid": pid,
            "running": self._is_alive(pid),
            "state": state,
            "supervision": supervision,
            "restart_allowed": time.time() >= supervision.get("cooldown_until", 0),
        }

    def start(self) -> dict:
        current = self.status()
        if current["running"]:
            return current
        if not current["restart_allowed"]:
            return current
        env = os.environ.copy()
        src_path = str(self.root_dir / "src")
        env["PYTHONPATH"] = src_path if not env.get("PYTHONPATH") else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
        process = subprocess.Popen(
            [sys.executable, "-m", "agent_os.main", "run"],
            cwd=self.root_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        self.pid_path.write_text(str(process.pid), encoding="utf-8")
        self._record_restart_attempt()
        return self.status()

    def stop(self) -> dict:
        pid = self._read_pid()
        if pid and self._is_alive(pid):
            os.kill(pid, signal.SIGTERM)
        self.state_path.write_text(json.dumps({"status": "stopped"}), encoding="utf-8")
        return self.status()

    def restart(self) -> dict:
        self.stop()
        return self.start()

    def _read_pid(self) -> int | None:
        if not self.pid_path.exists():
            return None
        try:
            return int(self.pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            return None

    def _is_alive(self, pid: int | None) -> bool:
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
        except OSError:
            return False

    def record_healthy_runtime(self) -> None:
        state = self._read_supervision_state()
        state["last_successful_start"] = time.time()
        self._write_supervision_state(state)

    def _read_supervision_state(self) -> dict:
        if not self.supervision_path.exists():
            return {
                "restart_count": 0,
                "last_restart_at": 0.0,
                "last_successful_start": 0.0,
                "cooldown_until": 0.0,
            }
        return json.loads(self.supervision_path.read_text(encoding="utf-8"))

    def _write_supervision_state(self, payload: dict) -> None:
        self.supervision_path.parent.mkdir(parents=True, exist_ok=True)
        self.supervision_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _record_restart_attempt(self) -> None:
        now = time.time()
        state = self._read_supervision_state()
        last_restart_at = float(state.get("last_restart_at", 0.0))
        restart_count = int(state.get("restart_count", 0))
        if now - last_restart_at > 300:
            restart_count = 0
        restart_count += 1
        state["restart_count"] = restart_count
        state["last_restart_at"] = now
        if restart_count >= 3:
            state["cooldown_until"] = now + 60
        self._write_supervision_state(state)
