# Agentic Hub

Agentic Hub is organized around a stable Python runtime plus DLC-style content packs.

The runtime now centers on one Telegram control bot, Vanta:

- slash commands are limited to operational lookups
- plain-English admin requests are handled by Vanta and translated into structured runtime actions
- catalog mutations default to runtime overrides rather than editing authored pack files

## Repo layout

- `src/agentic_hub/core/`: hub runtime, orchestration, task handling, approvals, memory, and state
- `src/agentic_hub/services/`: service implementations such as Telegram
- `src/agentic_hub/catalog/`: pack loading, validation, import/export, and registries
- `src/agentic_hub/models/`: shared schema/domain models
- `content/packs/basic/`: shipped baseline content pack
- `content/packs/<pack_id>/`: future DLC-style additions
- `data/runtime/`: generated state, logs, and catalog overrides
- `docs/`: authoring and repo structure docs

## Run

```bash
python -m agentic_hub
```

Or:

```bash
python main.py
```

## Content packs

Each pack contains a `manifest.json` plus one JSON file per object inside folders such as:

- `workers/`
- `tools/`
- `loadouts/`
- `worker_types/`
- `worker_roles/`
- `memory_policies/`

The shipped `basic` pack is the default baseline. Runtime edits are written to `data/runtime/catalog_overrides/` without mutating authored pack files.

## Worker interaction modes

Workers now declare an `interface_mode`:

- `managed`: owns its own Telegram bot token and talks through its own bot identity
- `internal`: only callable by runtime tasks, tools, or other workers
- `hybrid`: reserved for future use

Vanta remains the control bot. Managed worker bot registrations and Telegram conversation state are stored under `data/runtime/`.
