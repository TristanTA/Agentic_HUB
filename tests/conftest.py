from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture()
def repo_copy(tmp_path: Path) -> Path:
    src_root = Path(__file__).resolve().parents[1]
    ignore = shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__")
    shutil.copytree(src_root / "configs", tmp_path / "configs", ignore=ignore)
    shutil.copytree(src_root / "prompts", tmp_path / "prompts", ignore=ignore)
    shutil.copytree(src_root / "skills", tmp_path / "skills", ignore=ignore)
    if (src_root / "agent_specs").exists():
        shutil.copytree(src_root / "agent_specs", tmp_path / "agent_specs", ignore=ignore)
    if (src_root / "agents").exists():
        shutil.copytree(src_root / "agents", tmp_path / "agents", ignore=ignore)
    (tmp_path / "workspace" / "agent_tasks").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "generated").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    return tmp_path
