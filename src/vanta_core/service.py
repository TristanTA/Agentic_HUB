from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, request

from control_plane.commands import parse_management_command
from shared.schemas import VantaIncident
from specs.service import AgentSpecService
from storage.sqlite.db import SQLiteStore
from vanta_core.process_control import RuntimeProcessController


class VantaCoreService:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.store = SQLiteStore(root_dir / "data" / "hub.db")
        self.specs = AgentSpecService(root_dir)
        self.runtime = RuntimeProcessController(
            root_dir,
            root_dir / "data" / "agent_os.pid",
            root_dir / "data" / "agent_os_state.json",
        )
        self.incident_ledger_path = root_dir / "docs" / "vanta_incidents.md"
        self.provider_probe_path = root_dir / "data" / "provider_probe.json"

    def status(self) -> dict:
        return {
            "status": "ok",
            "vanta_state": self._compute_state(),
            "provider_ready": self.provider_status()["provider_ready"],
            "runtime": self.runtime.status(),
            "last_incident": self.latest_incident().get("incident"),
        }

    def runtime_status(self) -> dict:
        runtime = self.runtime.status()
        runtime["status"] = "ok"
        return runtime

    def provider_status(self) -> dict:
        ready = bool(os.getenv("OPENAI_API_KEY", "").strip())
        probe = self._probe_provider() if ready else {"probe_ok": False, "reason": "OPENAI_API_KEY is missing.", "checked_at": None}
        return {
            "status": "ok",
            "provider_ready": ready and probe["probe_ok"],
            "reason": "Provider responded successfully." if ready and probe["probe_ok"] else probe["reason"],
            "vanta_state": self._compute_state(provider_ready=ready and probe["probe_ok"]),
            "checked_at": probe["checked_at"],
        }

    def list_agents(self) -> dict:
        runtime_running = self.runtime.status()["running"]
        provider_ready = self.provider_status()["provider_ready"]
        return {
            "status": "ok",
            "agents": [
                {
                    **spec.model_dump(mode="json"),
                    "visibility": self.specs.explain_visibility(spec.id, runtime_running=runtime_running, provider_ready=provider_ready),
                }
                for spec in self.specs.list_specs()
            ],
        }

    def get_agent(self, agent_id: str) -> dict:
        spec = self.specs.get_spec(agent_id)
        if spec is None:
            return {"status": "error", "message": f"Unknown agent {agent_id}"}
        return {"status": "ok", "agent": spec.model_dump(mode="json")}

    def explain_agent(self, agent_id: str) -> dict:
        return {
            "status": "ok",
            "explanation": self.specs.explain_visibility(
                agent_id,
                runtime_running=self.runtime.status()["running"],
                provider_ready=self.provider_status()["provider_ready"],
            ),
        }

    def validate_agent(self, agent_id: str) -> dict:
        report = self.specs.validate_spec(agent_id)
        return {"status": "ok" if report.valid else "error", "validation": report.model_dump(mode="json")}

    def activate_agent(self, agent_id: str) -> dict:
        report = self.specs.activate_spec(agent_id)
        return {"status": "ok" if report.valid else "error", "validation": report.model_dump(mode="json")}

    def deactivate_agent(self, agent_id: str) -> dict:
        spec = self.specs.deactivate_spec(agent_id)
        if spec is None:
            return {"status": "error", "message": f"Unknown agent {agent_id}"}
        return {"status": "ok", "agent": spec.model_dump(mode="json")}

    def restart_runtime(self) -> dict:
        result = self.runtime.restart()
        if not result.get("running"):
            self.record_incident(
                component="agent_os",
                summary="Runtime restart failed",
                likely_cause="agent_os did not come back after restart request",
                failure_type="RuntimeRestartFailure",
                last_action="restart_runtime",
            )
        else:
            self.runtime.record_healthy_runtime()
        return {"status": "ok", "runtime": result}

    def latest_incident(self) -> dict:
        incident = self.store.latest_vanta_incident()
        if incident is None:
            return {"status": "ok", "message": "No incidents recorded."}
        return {"status": "ok", "incident": incident.model_dump(mode="json")}

    def record_incident(
        self,
        *,
        component: str,
        summary: str,
        likely_cause: str,
        failure_type: str,
        last_action: str,
        affected_agent: str = "vanta_core",
        severity: str = "high",
        details: dict | None = None,
    ) -> dict:
        incident = VantaIncident(
            incident_id=str(uuid.uuid4()),
            component=component,
            severity=severity,
            summary=summary,
            likely_cause=likely_cause,
            failure_type=failure_type,
            affected_agent=affected_agent,
            last_action=last_action,
            vanta_state=self._compute_state(),
            next_steps=["/status", "/runtime_status", "/incident"],
            details=details or {},
        )
        self.store.record_vanta_incident(incident)
        self._append_ledger(incident)
        return incident.model_dump(mode="json")

    def handle_command(self, text: str) -> dict:
        command = parse_management_command(text)
        if command is None:
            return {"status": "ignored"}
        if command.name == "status":
            return self.status()
        if command.name == "runtime_status":
            return self.runtime_status()
        if command.name == "provider_status":
            return self.provider_status()
        if command.name == "incident":
            return self.latest_incident()
        if command.name == "agents":
            return self.list_agents()
        if command.name == "agent":
            return self.get_agent(command.args[0]) if command.args else {"status": "error", "message": "Usage: /agent <id>"}
        if command.name == "explain_agent":
            return self.explain_agent(command.args[0]) if command.args else {"status": "error", "message": "Usage: /explain_agent <id>"}
        if command.name == "validate_agent":
            return self.validate_agent(command.args[0]) if command.args else {"status": "error", "message": "Usage: /validate_agent <id>"}
        if command.name == "activate_agent":
            return self.activate_agent(command.args[0]) if command.args else {"status": "error", "message": "Usage: /activate_agent <id>"}
        if command.name == "deactivate_agent":
            return self.deactivate_agent(command.args[0]) if command.args else {"status": "error", "message": "Usage: /deactivate_agent <id>"}
        if command.name == "restart_runtime":
            return self.restart_runtime()
        if command.name == "new_agent":
            return {"status": "interview_start"}
        return {"status": "error", "message": f"Unknown command /{command.name}"}

    def format_result(self, result: dict) -> str:
        if result.get("status") == "interview_start":
            return "Starting new agent interview."
        if "message" in result and len(result) <= 2:
            return result["message"]
        if "validation" in result:
            validation = result["validation"]
            return (
                f"Agent: {validation['agent_id']}\n"
                f"Valid: {validation['valid']}\n"
                f"Status: {validation['status_after_validation']}\n"
                f"Errors: {validation['errors'] or 'none'}"
            )
        if "explanation" in result:
            exp = result["explanation"]
            return f"Agent: {exp['agent_id']}\nVisible: {exp['visible']}\nReason: {exp['reason']}"
        if "agents" in result:
            rows = []
            for item in result["agents"]:
                rows.append(f"{item['id']} | {item['status']} | {item['visibility']['reason']}")
            return "\n".join(rows) or "No agents."
        if "agent" in result:
            agent = result["agent"]
            return f"{agent['id']} | {agent['role']} | {agent['interface']} | {agent['status']}"
        if "runtime" in result and "vanta_state" in result:
            return f"Vanta: {result['vanta_state']}\nProvider ready: {result['provider_ready']}\nRuntime: {result['runtime']}"
        if "runtime" in result:
            return str(result["runtime"])
        if "provider_ready" in result:
            return f"Provider ready: {result['provider_ready']}\nReason: {result['reason']}\nState: {result['vanta_state']}"
        if "incident" in result:
            incident = result["incident"]
            return f"Incident: {incident['summary']}\nComponent: {incident['component']}\nState: {incident['vanta_state']}"
        return str(result)

    def _compute_state(self, *, provider_ready: bool | None = None) -> str:
        runtime = self.runtime.status()
        latest_incident = self.store.latest_vanta_incident()
        if provider_ready is None:
            provider_ready = bool(os.getenv("OPENAI_API_KEY", "").strip())
        if not provider_ready and not runtime.get("running"):
            return "recovery_only"
        if not provider_ready:
            return "provider_down"
        if latest_incident is not None:
            return "incident_active"
        if not runtime.get("restart_allowed", True):
            return "degraded"
        if not runtime.get("running"):
            return "runtime_down"
        return "ready"

    def _probe_provider(self) -> dict:
        now = datetime.now(timezone.utc)
        if self.provider_probe_path.exists():
            cached = json.loads(self.provider_probe_path.read_text(encoding="utf-8"))
            checked_at = cached.get("checked_at")
            if checked_at:
                checked_time = datetime.fromisoformat(checked_at)
                if (now - checked_time).total_seconds() < 60:
                    return cached
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            result = {"probe_ok": False, "reason": "OPENAI_API_KEY is missing.", "checked_at": now.isoformat()}
            self._write_provider_probe(result)
            return result
        req = request.Request(
            "https://api.openai.com/v1/models/gpt-5.2",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        try:
            with request.urlopen(req, timeout=15) as response:
                response.read()
            result = {"probe_ok": True, "reason": "Provider responded successfully.", "checked_at": now.isoformat()}
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            result = {"probe_ok": False, "reason": f"OpenAI probe failed ({exc.code}): {detail[:200]}", "checked_at": now.isoformat()}
        except error.URLError as exc:
            result = {"probe_ok": False, "reason": f"OpenAI probe failed: {exc.reason}", "checked_at": now.isoformat()}
        self._write_provider_probe(result)
        return result

    def _write_provider_probe(self, payload: dict) -> None:
        self.provider_probe_path.parent.mkdir(parents=True, exist_ok=True)
        self.provider_probe_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _append_ledger(self, incident: VantaIncident) -> None:
        self.incident_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.incident_ledger_path.exists():
            self.incident_ledger_path.write_text("# Vanta Incident Ledger\n\n", encoding="utf-8")
        with self.incident_ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n".join(
                    [
                        f"## {incident.created_at.isoformat()} | {incident.severity} | {incident.component}",
                        f"- Summary: {incident.summary}",
                        f"- Likely cause: {incident.likely_cause}",
                        f"- Failure type: {incident.failure_type}",
                        f"- Last action: {incident.last_action}",
                        f"- State: {incident.vanta_state}",
                        "",
                    ]
                )
            )
