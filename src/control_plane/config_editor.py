from __future__ import annotations

from pathlib import Path

import yaml


class ConfigEditor:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir

    def _load_yaml(self, relative_path: str) -> tuple[Path, dict]:
        path = self.root_dir / relative_path
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return path, payload

    def _write_yaml(self, path: Path, payload: dict) -> None:
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def edit_markdown(self, relative_path: str, new_content: str) -> Path:
        path = self.root_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_content, encoding="utf-8")
        return path

    def set_enabled_flag(self, relative_path: str, section: str, item_id: str, enabled: bool) -> dict:
        path, payload = self._load_yaml(relative_path)
        for item in payload.get(section, []):
            if item.get("id") == item_id:
                item["enabled"] = enabled
                self._write_yaml(path, payload)
                return item
        raise ValueError(f"{item_id} not found in {relative_path}")

    def update_section_item(self, relative_path: str, section: str, item_id: str, updates: dict) -> dict:
        path, payload = self._load_yaml(relative_path)
        for item in payload.get(section, []):
            if item.get("id") == item_id:
                item.update(updates)
                self._write_yaml(path, payload)
                return item
        raise ValueError(f"{item_id} not found in {relative_path}")

    def append_section_item(self, relative_path: str, section: str, item: dict) -> dict:
        path, payload = self._load_yaml(relative_path)
        rows = payload.setdefault(section, [])
        item_id = item.get("id")
        if any(row.get("id") == item_id for row in rows):
            raise ValueError(f"{item_id} already exists in {relative_path}")
        rows.append(item)
        self._write_yaml(path, payload)
        return item

    def upsert_section_item(self, relative_path: str, section: str, item: dict) -> dict:
        path, payload = self._load_yaml(relative_path)
        rows = payload.setdefault(section, [])
        item_id = item.get("id")
        for existing in rows:
            if existing.get("id") == item_id:
                existing.update(item)
                self._write_yaml(path, payload)
                return existing
        rows.append(item)
        self._write_yaml(path, payload)
        return item

    def update_yaml_file(self, relative_path: str, updates: dict) -> dict:
        path, payload = self._load_yaml(relative_path)
        payload.update(updates)
        self._write_yaml(path, payload)
        return payload
