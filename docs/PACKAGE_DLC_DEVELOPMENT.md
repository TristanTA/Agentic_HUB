# Hub Package and DLC Development Guide

This guide is for developers who want to build a package or DLC for the hub.

It covers:
- what a package can contain
- how to define tools, worker types, roles, loadouts, memory policies, and workers
- how packages are imported
- how to point a tool at real Python code
- the current limitation around shipping executable code inside the package itself

## What a package is

A package is a folder or `.zip` file that contains:

- `manifest.json`
- optional `tools.json`
- optional `worker_types.json`
- optional `worker_roles.json`
- optional `loadouts.json`
- optional `memory_policies.json`
- optional `workers.json`

The hub imports these objects into the runtime catalog layer. They override nothing by default. If an imported object ID already exists, import fails unless the caller uses override mode.

## Quick start

Create a folder like this:

```text
my_music_dlc/
  manifest.json
  tools.json
  worker_types.json
  worker_roles.json
  loadouts.json
  memory_policies.json
  workers.json
```

Import it with:

```text
/catalog import C:\path\to\my_music_dlc
```

Or export the current runtime catalog into a starter package:

```text
/catalog export C:\path\to\exported_package
```

## Manifest format

`manifest.json` is required.

Example:

```json
{
  "package_id": "music_ops_pack",
  "name": "Music Ops Pack",
  "version": "1.0.0",
  "description": "Workers and tools for music-focused operations.",
  "dependencies": [],
  "conflicts": []
}
```

Fields:

- `package_id`: stable unique package ID
- `name`: human-readable package name
- `version`: package version string
- `description`: short description
- `dependencies`: package IDs this package expects
- `conflicts`: package IDs this package should not be installed with

Note: dependencies and conflicts are stored in the package but are not yet enforced by a dedicated dependency resolver. Keep them accurate anyway.

## Catalog object files

Each optional JSON file must contain a top-level array.

Example:

```json
[
  {
    "tool_id": "example_tool",
    "name": "Example Tool",
    "description": "Does an example action.",
    "implementation_ref": "hub.plugins.example_tools.run_example"
  }
]
```

The hub validates cross-references after merge. That means:

- a `loadout` can only reference tools that exist
- a `worker` can only reference a valid type, role, and loadout
- a `loadout.memory_policy_ref` must exist if set

## Tool definition format

Tools use the `ToolDefinition` schema.

Example `tools.json`:

```json
[
  {
    "tool_id": "music_lookup",
    "name": "Music Lookup",
    "description": "Look up artist and album data.",
    "capability_tags": ["music", "lookup", "research"],
    "input_schema_ref": null,
    "output_schema_ref": null,
    "safety_level": "low",
    "implementation_ref": "hub.plugins.music_tools.lookup_music",
    "enabled": true
  },
  {
    "tool_id": "music_notify",
    "name": "Music Notify",
    "description": "Send a music update to Telegram.",
    "capability_tags": ["music", "telegram", "messaging"],
    "safety_level": "medium",
    "implementation_ref": "hub.plugins.music_tools.notify_music",
    "enabled": true
  }
]
```

Important fields:

- `tool_id`: unique ID
- `name`: display name
- `description`: what the tool does
- `capability_tags`: tags for grouping and intent
- `safety_level`: `low`, `medium`, or `high`
- `implementation_ref`: Python import path for the actual code
- `enabled`: whether the tool is enabled after import

The hub adds `source`, `package_id`, and `updated_at` during import. You do not need to include them manually.

## Worker type format

Worker types describe execution behavior.

Example `worker_types.json`:

```json
[
  {
    "type_id": "music_agent_worker",
    "name": "Music Agent Worker",
    "execution_mode": "llm",
    "can_use_tools": true,
    "can_spawn_tasks": true,
    "can_request_approval": true,
    "can_emit_artifacts": true,
    "default_retry_policy": {},
    "allowed_task_kinds": ["research", "message", "playlist_plan"],
    "lifecycle_states": ["idle", "running", "paused", "failed"]
  }
]
```

Supported execution modes right now:

- `llm`
- `deterministic`
- `approval`

## Worker role format

Roles describe the worker’s job and behavioral framing.

Example `worker_roles.json`:

```json
[
  {
    "role_id": "playlist_curator",
    "name": "Playlist Curator",
    "purpose": "Build and refine playlist recommendations.",
    "behavior_guide_ref": "guides/playlist_curator.md",
    "default_output_style": "structured",
    "default_handoff_targets": ["reviewer"],
    "allowed_action_patterns": ["research:*", "message:*"],
    "blocked_action_patterns": ["delete:*"]
  }
]
```

## Memory policy format

Memory policies are optional but useful if your loadout needs memory controls.

Example `memory_policies.json`:

```json
[
  {
    "policy_id": "music_memory",
    "allowed_memory_types": ["working", "episodic", "semantic"],
    "retrieval_limits": {
      "episodic": 10,
      "semantic": 8
    },
    "allowed_tags": ["music", "artist", "album", "playlist"],
    "write_permissions": {
      "working": true,
      "episodic": true,
      "semantic": false
    },
    "promotion_rules_ref": null
  }
]
```

## Loadout format

Loadouts connect a worker to tools, policies, prompts, and tags.

Example `loadouts.json`:

```json
[
  {
    "loadout_id": "playlist_curator_core",
    "name": "Playlist Curator Core",
    "description": "Base loadout for playlist curation work.",
    "prompt_refs": ["prompts/playlist_curator.md"],
    "soul_ref": null,
    "skill_refs": [],
    "memory_policy_ref": "music_memory",
    "model_policy_ref": null,
    "approval_policy_ref": null,
    "artifact_policy_ref": null,
    "runtime_limits_ref": null,
    "allowed_tool_ids": ["music_lookup", "music_notify"],
    "tool_policy_overrides": {
      "music_notify": {
        "tool_id": "music_notify",
        "mode": "allow",
        "access_level": "execute",
        "require_approval": true
      }
    },
    "default_task_templates": [],
    "tags": ["music", "curation"]
  }
]
```

Important rule:

- Every tool in `allowed_tool_ids` must exist in the effective catalog.

## Worker instance format

Workers are the actual configured worker entries the dispatcher can select.

Example `workers.json`:

```json
[
  {
    "worker_id": "lyra",
    "name": "Lyra",
    "type_id": "music_agent_worker",
    "role_id": "playlist_curator",
    "loadout_id": "playlist_curator_core",
    "status": "enabled",
    "health": "healthy",
    "version": "1.0.0",
    "assigned_queues": ["default"],
    "tags": ["music", "playlist"],
    "enabled": false,
    "priority_bias": 2,
    "owner": "music_ops_pack",
    "notes": "Starts disabled until reviewed."
  }
]
```

Important behavior:

- New runtime-created workers default to `enabled: false`
- Package-defined workers should usually also start disabled unless you are very sure they should schedule immediately

## How to attach actual tool code

This is the important part.

`implementation_ref` is a Python import path string. Example:

```json
{
  "tool_id": "music_lookup",
  "implementation_ref": "hub.plugins.music_tools.lookup_music"
}
```

That means the actual Python code should look like this:

```python
# hub/plugins/music_tools.py

from __future__ import annotations

from typing import Any


def lookup_music(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query", "")
    return {
        "query": query,
        "matches": [],
        "ok": True,
    }


def notify_music(payload: dict[str, Any]) -> dict[str, Any]:
    chat_id = payload["chat_id"]
    text = payload["text"]
    return {
        "chat_id": chat_id,
        "text": text,
        "sent": True,
    }
```

So there are two parts:

1. The package JSON defines the tool metadata and references the function.
2. The Python module contains the actual callable implementation.

## Current limitation: package importer does not yet install Python code

Right now, the package/DLC system imports catalog JSON only.

It does **not** yet:

- copy Python files from the package into the repo
- install wheel files
- dynamically add a package folder to `sys.path`
- auto-import Python modules shipped inside the package directory

So today, if you want a package tool to point to real code, that code must already exist in a Python module the hub can import.

### Current supported pattern

Use a two-part delivery model:

1. Put the Python code in the hub codebase or another importable installed module.
2. Import the package JSON so the hub registers the tool, loadout, worker type, role, and worker objects.

Example:

- code lives in `hub/plugins/music_tools.py`
- package JSON references `hub.plugins.music_tools.lookup_music`

This works today.

### Not yet supported pattern

This is **not** automatic yet:

```text
my_music_dlc/
  manifest.json
  tools.json
  code/
    music_tools.py
```

The hub will currently import the JSON, but it will not automatically make `code/music_tools.py` executable or importable.

## Recommended package authoring workflow today

1. Write the Python implementation module first.
2. Choose stable IDs for tools, roles, types, loadouts, and workers.
3. Create `manifest.json`.
4. Create the JSON object files.
5. Make sure `implementation_ref` points at real importable Python code.
6. Import the package with `/catalog import <path>`.
7. Validate with:
   - `/catalog list tools`
   - `/catalog list loadouts`
   - `/catalog list workers`
   - `/runtime`

## Example end-to-end package

### `manifest.json`

```json
{
  "package_id": "music_ops_pack",
  "name": "Music Ops Pack",
  "version": "1.0.0",
  "description": "Music-focused workers and tools.",
  "dependencies": [],
  "conflicts": []
}
```

### `tools.json`

```json
[
  {
    "tool_id": "music_lookup",
    "name": "Music Lookup",
    "description": "Look up artist and album information.",
    "capability_tags": ["music", "research"],
    "safety_level": "low",
    "implementation_ref": "hub.plugins.music_tools.lookup_music",
    "enabled": true
  }
]
```

### `worker_types.json`

```json
[
  {
    "type_id": "music_agent_worker",
    "name": "Music Agent Worker",
    "execution_mode": "llm",
    "can_use_tools": true,
    "can_spawn_tasks": true,
    "can_request_approval": true,
    "can_emit_artifacts": true,
    "allowed_task_kinds": ["research", "message"]
  }
]
```

### `worker_roles.json`

```json
[
  {
    "role_id": "playlist_curator",
    "name": "Playlist Curator",
    "purpose": "Curate playlists and music recommendations.",
    "default_output_style": "structured"
  }
]
```

### `memory_policies.json`

```json
[
  {
    "policy_id": "music_memory",
    "allowed_memory_types": ["working", "episodic"]
  }
]
```

### `loadouts.json`

```json
[
  {
    "loadout_id": "playlist_curator_core",
    "name": "Playlist Curator Core",
    "memory_policy_ref": "music_memory",
    "allowed_tool_ids": ["music_lookup"]
  }
]
```

### `workers.json`

```json
[
  {
    "worker_id": "lyra",
    "name": "Lyra",
    "type_id": "music_agent_worker",
    "role_id": "playlist_curator",
    "loadout_id": "playlist_curator_core",
    "enabled": false,
    "priority_bias": 1,
    "owner": "music_ops_pack"
  }
]
```

## Validation rules to keep in mind

Your package will fail to import if:

- `manifest.json` is missing
- JSON is malformed
- a `loadout` references a missing tool
- a `loadout` references a missing memory policy
- a `worker` references a missing type, role, or loadout
- any object ID conflicts with an existing object and override mode is not enabled

## Command reference

Useful commands while developing:

```text
/catalog list tools
/catalog list worker_types
/catalog list worker_roles
/catalog list loadouts
/catalog list memory_policies
/catalog list workers
/catalog import C:\path\to\my_package
/catalog import C:\path\to\my_package --override
/catalog export C:\path\to\exported_package
/runtime
```

## Best practices

- Keep IDs stable and lowercase
- Start package workers disabled
- Keep tool names human-readable but IDs machine-stable
- Use `implementation_ref` paths that are easy to grep and test
- Prefer one Python module per package domain, such as `hub.plugins.music_tools`
- Keep roles focused on intent, and types focused on execution behavior
- Keep loadouts small and composable

## Recommended future enhancement

If we want true self-contained DLCs, the next upgrade should add package code support such as:

- a `code/` directory inside the package
- package-local Python module loading
- validation that every `implementation_ref` resolves at import time
- optional signed packages or allowed-package directories

That would let a package deliver both:

- catalog objects
- executable tool code

Today, the catalog side is implemented. The code-shipping side is not yet automatic.
