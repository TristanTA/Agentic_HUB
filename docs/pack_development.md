# Pack Development

Content packs are the extension surface for Agentic Hub.

## Structure

Each pack lives under `content/packs/<pack_id>/` and must include:

- `manifest.json`
- `workers/*.json`
- `tools/*.json`
- `loadouts/*.json`
- `worker_types/*.json`
- `worker_roles/*.json`
- `memory_policies/*.json`

Only the folders you need have to exist.

## Manifest

Required manifest fields:

- `pack_id`
- `name`
- `version`
- `description`
- `dependencies`
- `conflicts`
- `enabled_by_default`

## Authoring model

- One object per file keeps diffs and reviews clean.
- Pack files are authored content.
- Runtime changes belong in `data/runtime/catalog_overrides/`.
- Packs can add workers, tools, loadouts, worker types, worker roles, and memory policies.

## Import/export

The catalog manager supports importing a folder or zip pack and exporting runtime overrides as a pack-shaped directory or zip archive.
