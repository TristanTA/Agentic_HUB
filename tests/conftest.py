from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture()
def repo_copy(tmp_path: Path) -> Path:
    src_root = Path(__file__).resolve().parents[1]
    ignore = shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__")
    if (src_root / "agent_specs").exists():
        shutil.copytree(src_root / "agent_specs", tmp_path / "agent_specs", ignore=ignore)
    (tmp_path / "workspace" / "agent_tasks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "generated").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    return tmp_path
