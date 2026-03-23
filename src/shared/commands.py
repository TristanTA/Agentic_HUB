from __future__ import annotations

import shlex
from dataclasses import dataclass, field


@dataclass(slots=True)
class ManagementCommand:
    name: str
    args: list[str] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)


def parse_management_command(text: str) -> ManagementCommand | None:
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None

    parts = shlex.split(raw)
    if not parts:
        return None

    name = parts[0][1:].strip().lower()
    if "@" in name:
        name = name.split("@", 1)[0]
    args: list[str] = []
    options: dict[str, str] = {}

    i = 1
    while i < len(parts):
        token = parts[i]
        if token.startswith("--"):
            key = token[2:].strip().replace("-", "_")
            if not key:
                i += 1
                continue
            value = "true"
            if i + 1 < len(parts) and not parts[i + 1].startswith("--"):
                value = parts[i + 1]
                i += 1
            options[key] = value
        else:
            args.append(token)
        i += 1

    return ManagementCommand(name=name, args=args, options=options)
