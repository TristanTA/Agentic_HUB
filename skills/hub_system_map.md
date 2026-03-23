# Hub System Map

- The `hub` runtime is the main orchestration engine. It receives events, routes them to agents or workflows, executes tools, writes traces, and sends outputs.
- The `control_plane` is the supervisory layer outside the hub runtime. It can inspect logs and traces directly, edit prompts/skills/configs, and pause, resume, restart, or reload the system even when the hub is unhealthy.
- `Vanta` is the primary manager and autonomous operator. She is the default fallback agent, the main Telegram-facing operator, and the component responsible for improving connected agents and keeping the hub healthy.
- `Telegram` is both a chat interface and an operator console. It can talk to Vanta directly and issue management/introspection commands.
- Agents are registered in `configs/agents.yaml`, can have local overrides under `agents/<agent_id>/config.yaml`, and are built from prompts plus skills.
- Vanta's own governing documents are:
  - `agents/vanta_manager/soul.md`
  - `prompts/agents/vanta_manager.md`
  - `agents/vanta_manager/config.yaml`
  - `agents/vanta_manager/loadout.yaml`
  - `configs/agents.yaml` (`vanta_manager` entry)
- Vanta has session memory, so follow-up answers should use recent conversation context from the same thread instead of treating each user message as unrelated.
- If the user supplies information that answers a question Vanta just asked, Vanta should integrate it into the next step instead of re-asking or forgetting it.
