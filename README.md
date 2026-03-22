# Personal AI Hub

Personal AI Hub is a self-hosted orchestration repo for running personal agents behind one local runtime while keeping management and recovery outside that runtime.

## Architecture

The system has two independent processes:

- `hub`: receives inputs, routes deterministically, executes LangChain-built agents/tools/workflows, and writes traces.
- `control_plane`: supervises the hub, reads logs/configs directly, edits prompts and skills, and handles pause/resume/restart even when the hub is unhealthy.

Agents are configured from YAML, built from Markdown prompts plus Markdown skill packs, and can hand work to each other through hub-managed Markdown task/result files.

## Run locally

```bash
pip install -e .[dev]
start_hub_and_vanta.bat
```

The batch file opens two windows:

- the hub runtime, which loads `vanta_manager` from `configs/agents.yaml`
- the control plane server

If port `8011` is already in use, the batch file skips starting a second control-plane window.

If you prefer to run them manually instead of using the batch file:

```bash
hub-runtime
hub-control serve
```

Telegram is now part chat surface, part operator console. It supports direct agent messaging, management commands, and Vanta introspection commands while a live bot runner polls for updates.

Vanta also has an ambient operator loop that can review hub health, agent effectiveness, and recent lessons even when no one is actively chatting with her.

## Migrating an existing agent

1. Add a prompt in `prompts/agents/`.
2. Add any reusable skills in `skills/`.
3. Register the agent in `configs/agents.yaml`.
4. Bind allowed tools and a preferred model.
5. If needed, add a thin adapter under `src/hub/agents/`.

## Testing

```bash
pytest
```
