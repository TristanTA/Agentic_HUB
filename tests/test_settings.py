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
