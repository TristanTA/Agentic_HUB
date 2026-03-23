# Vanta OS

Vanta OS is a fresh rebuild centered on an ultra-robust Vanta supervisor and a minimal Agent OS runtime.

## Architecture

The system has two new layers:

- `vanta_core`: the always-on supervisor that owns Telegram operations, provider checks, incident reporting, agent visibility, validation, activation, and runtime recovery.
- `agent_os`: a small worker runtime that loads only active validated agents from generated runtime registry data.

Canonical agent definitions live in `agent_specs/`. Those specs are the source of truth. The runtime registry in `generated/` is derived from them.

## Start The System

Use the single launcher:

```bat
start_vanta_os.bat
```

That starts Vanta Core, and Vanta Core supervises Agent OS from there.

## Telegram Commands

Vanta v1 exposes a compact operator surface:

- `/status`
- `/runtime_status`
- `/provider_status`
- `/incident`
- `/agents`
- `/agent <id>`
- `/explain_agent <id>`
- `/restart_runtime`
- `/validate_agent <id>`
- `/activate_agent <id>`
- `/deactivate_agent <id>`
- `/new_agent`

## Testing

```bash
pytest
```
