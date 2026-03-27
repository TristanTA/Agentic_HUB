from __future__ import annotations

import difflib
import subprocess
from pathlib import Path


class RepoTools:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()

    def search_files(self, query: str, *, limit: int = 20) -> list[dict[str, object]]:
        query_lower = query.lower()
        matches: list[dict[str, object]] = []
        for path in self.repo_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part.startswith(".git") or part == "__pycache__" for part in path.parts):
                continue
            rel_path = path.relative_to(self.repo_root).as_posix()
            if query_lower in rel_path.lower():
                matches.append({"path": rel_path, "line": None, "snippet": rel_path})
                if len(matches) >= limit:
                    break
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            except OSError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if query_lower in line.lower():
                    matches.append({"path": rel_path, "line": line_number, "snippet": line.strip()[:200]})
                    if len(matches) >= limit:
                        return matches
        return matches

    def read_file(self, relative_path: str) -> str:
        path = self._resolve_path(relative_path)
        return path.read_text(encoding="utf-8")

    def write_file(self, relative_path: str, content: str) -> None:
        path = self._resolve_path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete_file(self, relative_path: str) -> None:
        path = self._resolve_path(relative_path)
        if path.exists():
            path.unlink()

    def preview_diff(self, relative_path: str, new_content: str) -> str:
        path = self._resolve_path(relative_path)
        old_content = path.read_text(encoding="utf-8") if path.exists() else ""
        diff = difflib.unified_diff(
            old_content.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            lineterm="",
        )
        return "\n".join(diff)

    def git_diff(self) -> str:
        result = subprocess.run(
            ["git", "diff", "--", "."],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip()

    def run_command(self, command: str) -> dict[str, object]:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }

    def _resolve_path(self, relative_path: str) -> Path:
        path = (self.repo_root / relative_path).resolve()
        if self.repo_root not in path.parents and path != self.repo_root:
            raise ValueError(f"Path escapes repository root: {relative_path}")
        return path
