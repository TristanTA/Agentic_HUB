from __future__ import annotations

import difflib
import subprocess
from pathlib import Path


class RepoTools:
    @staticmethod
    def _resolve(project_root: str | Path, relative_path: str) -> Path:
        root = Path(project_root).resolve()
        target = (root / relative_path).resolve()
        if root not in target.parents and target != root:
            raise ValueError(f"Path escapes project root: {relative_path}")
        return target

    @staticmethod
    def read_file(project_root: str | Path, relative_path: str, *, encoding: str = "utf-8") -> str:
        return RepoTools._resolve(project_root, relative_path).read_text(encoding=encoding)

    @staticmethod
    def write_file(project_root: str | Path, relative_path: str, content: str, *, encoding: str = "utf-8") -> dict:
        path = RepoTools._resolve(project_root, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return {"ok": True, "path": str(path)}

    @staticmethod
    def delete_file(project_root: str | Path, relative_path: str) -> dict:
        path = RepoTools._resolve(project_root, relative_path)
        if path.exists():
            path.unlink()
        return {"ok": True, "path": str(path)}

    @staticmethod
    def list_directory(project_root: str | Path, relative_path: str = ".", *, include_hidden: bool = False) -> list[str]:
        path = RepoTools._resolve(project_root, relative_path)
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(relative_path)
        items = []
        for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
            if not include_hidden and child.name.startswith("."):
                continue
            items.append(str(child.relative_to(Path(project_root).resolve())).replace("\\", "/"))
        return items

    @staticmethod
    def search_files(project_root: str | Path, query: str, *, suffixes: tuple[str, ...] = (".py", ".json", ".md", ".txt")) -> list[dict]:
        root = Path(project_root).resolve()
        query_lower = query.lower()
        matches: list[dict] = []
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if query_lower in line.lower():
                    matches.append(
                        {
                            "path": str(path.relative_to(root)).replace("\\", "/"),
                            "line_number": line_number,
                            "line": line.strip(),
                        }
                    )
                    break
        return matches

    @staticmethod
    def preview_diff(project_root: str | Path, relative_path: str, new_content: str, *, encoding: str = "utf-8") -> str:
        path = RepoTools._resolve(project_root, relative_path)
        old_content = path.read_text(encoding=encoding).splitlines() if path.exists() else []
        diff = difflib.unified_diff(
            old_content,
            new_content.splitlines(),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            lineterm="",
        )
        return "\n".join(diff)

    @staticmethod
    def run_command(project_root: str | Path, command: list[str], *, timeout_seconds: int = 30) -> dict:
        completed = subprocess.run(
            command,
            cwd=str(Path(project_root).resolve()),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
