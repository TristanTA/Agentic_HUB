from __future__ import annotations

import os
from pathlib import Path

from shared.settings import AppSettings


def test_settings_loads_env_example_values(tmp_path: Path, monkeypatch):
    (tmp_path / ".env.example").write_text(
        "HUB_ENV=production\nCONTROL_PLANE_PORT=9001\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("HUB_ENV", raising=False)
    monkeypatch.delenv("CONTROL_PLANE_PORT", raising=False)

    settings = AppSettings.load(tmp_path)

    assert settings.env == "production"
    assert settings.control_plane_port == 9001


def test_settings_repo_file_overrides_stale_shell_env(tmp_path: Path, monkeypatch):
    (tmp_path / ".env.example").write_text(
        "HUB_ENV=production\nCONTROL_PLANE_PORT=9001\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HUB_ENV", "stale")
    monkeypatch.setenv("CONTROL_PLANE_PORT", "7777")

    settings = AppSettings.load(tmp_path)

    assert settings.env == "production"
    assert settings.control_plane_port == 9001


def test_settings_dotenv_overrides_env_example(tmp_path: Path, monkeypatch):
    (tmp_path / ".env.example").write_text(
        "HUB_ENV=production\nCONTROL_PLANE_PORT=9001\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "HUB_ENV=local\nCONTROL_PLANE_PORT=8111\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("HUB_ENV", raising=False)
    monkeypatch.delenv("CONTROL_PLANE_PORT", raising=False)

    settings = AppSettings.load(tmp_path)

    assert settings.env == "local"
    assert settings.control_plane_port == 8111
