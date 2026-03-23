from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    root_dir: Path
    env: str
    control_plane_host: str
    control_plane_port: int

    @property
    def config_dir(self) -> Path:
        return self.root_dir / "configs"

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def logs_dir(self) -> Path:
        return self.root_dir / "logs"

    @property
    def prompts_dir(self) -> Path:
        return self.root_dir / "prompts"

    @property
    def agent_specs_dir(self) -> Path:
        return self.root_dir / "agent_specs"

    @property
    def generated_dir(self) -> Path:
        return self.root_dir / "generated"

    @property
    def skills_dir(self) -> Path:
        return self.root_dir / "skills"

    @property
    def workspace_dir(self) -> Path:
        return self.root_dir / "workspace"

    @classmethod
    def load(cls, root_dir: str | Path | None = None) -> "AppSettings":
        initial_base = Path(root_dir or os.getenv("HUB_HOME") or Path.cwd()).resolve()
        _load_env_file(initial_base)
        base = Path(root_dir or os.getenv("HUB_HOME") or Path.cwd()).resolve()
        return cls(
            root_dir=base,
            env=os.getenv("HUB_ENV", "development"),
            control_plane_host=os.getenv("CONTROL_PLANE_HOST", "127.0.0.1"),
            control_plane_port=int(os.getenv("CONTROL_PLANE_PORT", "8011")),
        )

    def ensure_directories(self) -> None:
        for path in [
            self.config_dir,
            self.data_dir,
            self.agent_specs_dir,
            self.generated_dir,
            self.logs_dir,
            self.prompts_dir,
            self.skills_dir,
            self.root_dir / "agents",
            self.workspace_dir / "agent_tasks",
        ]:
            path.mkdir(parents=True, exist_ok=True)


def _load_env_file(root_dir: Path) -> None:
    for filename in [".env", ".env.example"]:
        path = root_dir / filename
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
