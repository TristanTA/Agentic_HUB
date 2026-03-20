# ARIA-Style Remodel Proposal

## Why Remodel

`ARIA` is easier to reason about because the runtime is organized around the things that actually matter at execution time:

- agents
- tools
- loadouts
- souls
- skills
- long-term memory

`Agentic_HUB` already has many of those concepts, but they are currently spread across generic YAML registries, prompt folders, and runtime internals. That makes the system flexible, but less legible.

The goal of this remodel is to keep the good parts of the hub:

- deterministic routing
- trace storage
- management/control-plane separation
- future multi-agent workflows

while changing the project shape so it feels more like `ARIA`:

- clearer to build a new agent
- clearer to build a new tool
- clearer to assign a tool set to an agent
- clearer to define personality and reusable instructions
- clearer to support durable memory

## Main Recommendation

Keep the current hub runtime architecture, but remodel the project around first-class runtime packages instead of central registries.

In practice:

- keep `control_plane`
- keep `router`
- keep `workflow` execution
- keep SQLite tracing
- replace most YAML-first composition with file-and-module-first composition

## Proposed Target Structure

```text
Agentic_HUB/
  agents/
    general_assistant/
      agent.py
      soul.md
      loadout.py
      config.yaml
    planner/
      agent.py
      soul.md
      loadout.py
      config.yaml
  tools/
    base.py
    filesystem_tools.py
    memory_tools.py
    web_tools.py
    workspace_tools.py
    packages.py
    loadouts/
      default_loadout.py
      planner_loadout.py
  skills/
    writing/
      skill.md
    planning/
      skill.md
  memory/
    memory_db.py
    schemas.py
    repositories/
  runtime/
    app.py
    service.py
    router.py
    workflows.py
  server/
    telegram.py
    web_api.py
  control_plane/
    ...
  storage/
    traces.py
    state.py
  docs/
    aria-style-remodel.md
```

## Concept Mapping

### 1. Agents

Current hub:

- agent identity lives in `configs/agents.yaml`
- personality lives in prompt markdown
- skills live in separate config and markdown files

Target style:

- each agent gets its own folder
- each agent owns:
  - `soul.md`
  - `loadout.py`
  - `config.yaml`
  - optional `agent.py` adapter

This makes agent creation feel like:

1. create a folder
2. write the soul
3. choose the loadout
4. set model and memory scope

instead of editing several central registries.

### 2. Tools

Current hub:

- tools are described in YAML
- only a small built-in tool set is actually implemented

Target style:

- tools are real Python modules first
- optional metadata can still exist, but next to the tool code
- each tool should have:
  - stable id
  - description
  - input schema
  - side-effect level
  - invoke function

This matches the clarity of `ARIA`, where tool creation is mostly "write a tool module, then include it in a loadout."

### 3. Loadouts

This is the biggest missing concept in `Agentic_HUB`.

`ARIA` is very clear here:

- tools exist independently
- a loadout is the selected package of tools for an agent

The hub should adopt this directly.

Recommended pattern:

- add `tools/packages.py` with a `ToolsPackage` or `Loadout` abstraction
- each loadout explicitly returns the tools that an agent can use
- agents reference a loadout id or loadout module, not raw tool ids

That gives you:

- reusable tool sets
- smaller agent definitions
- easier security review
- easier environment-specific overrides

### 4. `skill.md` and `soul.md`

These should be separate concepts.

Use `soul.md` for:

- identity
- goals
- behavior rules
- long-lived operating principles

Use `skill.md` for:

- reusable procedural guidance
- domain-specific checklists
- narrow task playbooks

That separation is already implied in the hub, but `ARIA` expresses it more clearly. The remodel should make it explicit in the filesystem and in the agent loader.

### 5. Long-Term Memory

`ARIA` has the better mental model:

- event log
- stable facts
- summaries

The hub currently stores run traces, health, and management audit, but not agent-facing long-term memory as a first-class subsystem.

Recommended upgrade:

- keep existing trace/audit tables
- add a separate memory subsystem for agent cognition
- expose memory through actual tools

Suggested tables:

- `memory_events`
- `memory_facts`
- `memory_summaries`
- `agent_threads`

This should be separate from operational tracing:

- tracing answers: what did the system do?
- memory answers: what should the agent remember?

## Loader Direction

The loader should shift from "assemble everything from global registries" to "discover runtime objects from folders."

Recommended approach:

- bootstrap scans `agents/*/config.yaml`
- each agent config points to:
  - `soul.md`
  - `loadout.py` or loadout id
  - skill ids or skill paths
  - model
  - memory policy
- tools are imported from Python modules, not reconstructed from YAML

You can still keep a small global registry for:

- routing rules
- model providers
- deployment settings

but agents and tools should stop being primarily registry-driven.

## Deployment Direction

The runtime should be transport-agnostic.

That means the same core should run in two modes:

- desktop/local mode
- hosted web service mode

### Shared core

Shared regardless of environment:

- agent loading
- souls
- skills
- tool loadouts
- router
- workflow execution
- SQLite or Postgres-backed memory/traces

### Environment adapters

Only these should vary:

- input adapter
- output adapter
- deployment config
- storage backend wiring

Examples:

- desktop: local Telegram poller, local filesystem workspace, SQLite
- Render: FastAPI backend, webhook ingestion, persistent disk or Postgres, environment variables for secrets

## Best Path For Render

If you want this running on Render as a backend service, design toward:

- FastAPI app as the hosted entrypoint
- webhook-based integrations instead of polling where possible
- stateless request handlers
- persistent storage outside the ephemeral container filesystem

Recommended production split:

- app/runtime layer: pure Python service
- transport layer: FastAPI endpoints or webhook handlers
- persistence layer:
  - SQLite for local/dev
  - Postgres for hosted production if the project grows

SQLite is still fine for early hosted experiments if Render gives you persistent disk and you accept the tradeoffs.

## Telegram-Native Builder

One of the most valuable upgrades would be to let the manager agent create and modify runtime assets directly from Telegram slash commands.

This would make the system feel native and self-hosted in the best way:

- no CLI required for common setup work
- no manual file editing for routine agent creation
- easier remote management from phone or desktop Telegram
- much better fit for a continuously running personal hub

### Core idea

Use Telegram as the operator interface, but keep file creation and system mutation behind a dedicated management workflow.

That means:

- user sends a slash command in Telegram
- command is normalized into a management request
- manager agent gathers missing details if needed
- builder workflow generates files and config updates
- changes are validated
- hub reload is offered or performed
- full audit record is stored

### Recommended commands

Good first commands:

- `/new_agent`
- `/new_tool`
- `/new_skill`
- `/new_soul`
- `/new_loadout`
- `/edit_agent`
- `/enable_agent`
- `/disable_agent`
- `/reload`
- `/status`

### Example flows

`/new_agent researcher`

Expected conversational flow:

1. manager asks for purpose
2. manager asks which tools or loadout it should use
3. manager asks whether to create a new soul or reuse one
4. manager asks which skills to attach
5. manager generates the files
6. manager reports what was created and whether reload is needed

`/new_tool weather_lookup`

Expected flow:

1. manager asks what the tool should do
2. manager asks for input shape
3. manager asks whether it has side effects
4. manager writes a Python tool module stub plus metadata
5. manager offers to add it to a loadout

### Safety model

This should not be a free-form "agent can rewrite the whole repo" capability.

It should be scoped behind explicit management actions.

Recommended safety rules:

- only accept management slash commands from approved Telegram chat IDs
- separate read-only assistant behavior from mutating builder behavior
- require confirmation before creating or editing executable Python tools
- require confirmation before reloading or restarting the hub
- write all mutations to management audit logs
- validate generated files before enabling them

### Architecture shape

The cleanest design is a dedicated builder subsystem.

Suggested pieces:

- `server/telegram.py`
  - parses slash commands and chat permissions
- `control_plane/command_router.py`
  - turns slash commands into structured management intents
- `control_plane/builder_service.py`
  - owns generation and update flows
- `control_plane/scaffolders/`
  - agent scaffolder
  - tool scaffolder
  - skill scaffolder
  - soul scaffolder
  - loadout scaffolder
- `control_plane/validators/`
  - config validator
  - import validator
  - prompt/markdown validator

### Important distinction

There should be two manager modes:

- advisor mode
  - inspect status
  - summarize issues
  - suggest changes
- builder mode
  - create files
  - edit configs
  - enable or disable runtime assets

That split keeps normal conversations safe while still allowing powerful operator workflows.

### Best implementation pattern

For reliability, slash commands should produce structured actions, not just free-form prompts.

Recommended approach:

- slash command maps to a typed action like `create_agent`
- action has required fields and validation
- manager agent helps fill missing fields conversationally
- scaffolder writes deterministic file templates
- LLM is used for content generation inside templates, not for arbitrary repo mutation

This keeps the "smart" part where it helps, while preserving predictability.

### Suggested first slice

The best first Telegram-native builder feature is:

1. `/new_agent`
2. create agent folder
3. create `soul.md`
4. create `config.yaml`
5. attach an existing loadout
6. optionally attach existing skills
7. register or reload

That single workflow would prove the whole concept and unlock the most value quickly.

## Suggested Migration Phases

### Phase 1: Reshape without changing behavior

- create first-class `agents/`, `tools/`, `memory/`, and `server/` packages
- introduce `soul.md` files for existing agents
- introduce loadout modules
- keep current router and control plane intact

### Phase 2: Move agent definitions out of central YAML

- move agent config into per-agent folders
- update loader to discover agents from folders
- reduce `configs/agents.yaml` to routing or legacy compatibility only

### Phase 3: Add real agent memory

- create memory subsystem separate from run tracing
- expose memory read/write/search tools
- define memory policies by agent or loadout

### Phase 4: Add hosted server mode

- add `server/web_api.py`
- expose `/health`, `/ingest`, `/runs/{id}`, `/agents`
- keep local mode as a thin wrapper around the same runtime

## Concrete Recommendation For This Repo

The best near-term move is not a rewrite.

The best move is:

1. keep the current `HubRuntime`, router, workflows, and control plane
2. add ARIA-style folders and abstractions alongside them
3. migrate one agent end-to-end as the reference pattern
4. only remove the old registry style after the new path is working

That gets you the clarity you want without losing the more advanced hub features you already built.

## Good Design Rules To Preserve

- agents should be easy to inspect from one folder
- loadouts should be the permission boundary
- souls should define identity, not task checklists
- skills should be composable and reusable
- memory should be separate from operational logs
- runtime core should not care whether it is running on a home desktop or Render

## First Refactor I Would Do

If we start implementation, the first slice should be:

1. add a `Loadout` abstraction modeled after `ARIA`
2. add per-agent folders with `soul.md`
3. change the agent builder to read soul plus skills from the agent folder
4. keep routing and control-plane config where they are for now

That would give the repo the biggest clarity win with the lowest rewrite risk.
