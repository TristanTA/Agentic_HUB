from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from hub.inputs.normalize import normalize_telegram_payload
from hub.outputs.telegram import TelegramOutputAdapter
from shared.schemas import VantaLesson, VantaReviewCycle


class VantaOperator:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self._cycle_count = 0

    def run_once(self, trigger: str = "ambient") -> dict:
        self._cycle_count += 1
        status = self.runtime.hub_status()
        workers = self.runtime.adapters.health_report()
        tasks = [task.model_dump(mode="json") for task in self.runtime.task_service.list_tasks(limit=10)]
        recent_errors = self.runtime.store.recent_errors(limit=5)
        recent_lessons = self.runtime.list_vanta_lessons(limit=5)
        control = getattr(self.runtime, "control_plane", None)
        focus_payload = control.vanta_focus() if control is not None else {"focus_area": "agent_effectiveness", "target": "unknown", "reason": ""}
        recent_changes = self.runtime.store.list_vanta_changes(limit=5)

        findings: list[str] = []
        concerns: list[str] = []
        focus_area = focus_payload.get("focus_area", "agent_effectiveness")

        degraded = [item["agent_id"] for item in workers if item.get("status") != "ok"]
        if degraded:
            focus_area = "hub_health"
            findings.append(f"Degraded workers: {', '.join(degraded)}")
            concerns.append("Worker health is degraded.")
        if recent_errors:
            focus_area = "hub_health"
            findings.append(f"Recent error count: {len(recent_errors)}")
            concerns.append("Recent runtime failures detected.")
        queued = [task for task in tasks if task.get("status") in {"queued", "failed"}]
        if queued:
            findings.append(f"Outstanding weak tasks: {len(queued)}")
        if not findings:
            findings.append(f"No urgent faults detected; focus target is {focus_payload.get('target', 'unknown')}.")

        summary = (
            "Vanta reviewed agent effectiveness first and hub health second."
            if focus_area == "agent_effectiveness"
            else "Vanta reviewed hub health because faults were detected."
        )
        findings.append(f"Chosen focus target: {focus_payload.get('target', 'unknown')}")
        if focus_payload.get("reason"):
            findings.append(f"Focus rationale: {focus_payload['reason']}")

        actions_taken: list[str] = []
        lesson_ids: list[str] = []
        if recent_errors:
            lesson = VantaLesson(
                lesson_id=str(uuid.uuid4()),
                category="failed_or_weak_outcome",
                situation="Recent runtime errors were present during an ambient review.",
                action_taken="Prioritized hub-health review before new improvement work.",
                outcome="System health concerns were surfaced for follow-up.",
                mistake="Do not assume the hub is stable when recent errors exist.",
                updated_rule="Inspect recent errors before changing prompts, routes, or agent behavior.",
            )
            self.runtime.record_vanta_lesson(lesson)
            lesson_ids.append(lesson.lesson_id)
            actions_taken.append("Recorded a system-stability lesson for Vanta.")
        for change in recent_changes:
            if change.rolled_back_at or change.evaluated_at:
                continue
            note = "No recent runtime errors after this change." if not recent_errors else "Recent runtime errors still exist after this change."
            self.runtime.store.evaluate_vanta_change(change.change_id, datetime.now(timezone.utc).isoformat(), note)
            actions_taken.append(f"Evaluated change {change.change_id}.")

        review = VantaReviewCycle(
            review_id=str(uuid.uuid4()),
            trigger=trigger,
            focus_area=focus_area,
            summary=summary,
            findings=findings,
            actions_taken=actions_taken,
            open_concerns=concerns,
            lessons_recorded=lesson_ids,
        )
        self.runtime.record_vanta_review(review)

        if self.runtime.bundle.hub_config.vanta.enabled:
            prompt = self._build_review_prompt(review, recent_lessons)
            event = normalize_telegram_payload(
                {
                    "thread_id": "system:vanta",
                    "message": {"text": prompt, "chat": {"id": "system:vanta"}, "message_id": str(uuid.uuid4())},
                    "text": prompt,
                }
            )
            event.metadata["system_trigger"] = trigger
            self.runtime.process_event_for_agent(event, "vanta_manager", output_adapter=TelegramOutputAdapter(enabled=False))

        return review.model_dump(mode="json")

    def run_forever(self) -> None:
        interval = max(30, int(self.runtime.bundle.hub_config.vanta.interval_seconds))
        while True:
            try:
                self.run_once(trigger="ambient")
            except Exception as exc:
                self.runtime.logger.log("vanta.review_failed", {"error": str(exc)})
            time.sleep(interval)

    def _build_review_prompt(self, review: VantaReviewCycle, recent_lessons: list[dict]) -> str:
        lesson_lines = "\n".join(
            f"- {item['category']}: {item['updated_rule']}" for item in recent_lessons[:3]
        ) or "- No recent lessons recorded."
        findings = "\n".join(f"- {item}" for item in review.findings)
        concerns = "\n".join(f"- {item}" for item in review.open_concerns) or "- No open concerns."
        return "\n".join(
            [
                "Autonomous Vanta review cycle.",
                f"Focus area: {review.focus_area}",
                "Findings:",
                findings,
                "Open concerns:",
                concerns,
                "Recent lessons:",
                lesson_lines,
                "Your priorities:",
                "1. Improve connected agents.",
                "2. Keep the hub healthy and resolve faults.",
                "Act autonomously, think deeply, challenge weak assumptions, and improve yourself when that raises future leverage.",
            ]
        )
