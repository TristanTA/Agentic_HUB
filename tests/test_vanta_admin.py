from __future__ import annotations

from pathlib import Path
from agentic_hub.core.hub import Hub


def build_hub(tmp_path: Path) -> Hub:
    hub = Hub(register_services=False)
    hub.telegram_runtime_manager.env_path = tmp_path / ".env"
    hub.telegram_runtime_manager.managed_bot_store.path = tmp_path / "managed_telegram_bots.json"
    hub.telegram_runtime_manager.session_store.path = tmp_path / "telegram_conversation_sessions.json"
    hub.catalog_manager.overrides_dir = tmp_path / "catalog_overrides"
    for store in hub.catalog_manager.override_stores.values():
        store.path = tmp_path / "catalog_overrides" / store.path.name
    hub.catalog_manager.reload_catalog()
    hub.skill_library.runtime_dir = tmp_path
    hub.skill_library.skills_dir = tmp_path / "skills"
    hub.skill_library.document_store.path = tmp_path / "skill_library.json"
    hub.skill_library.gap_store.path = tmp_path / "skill_gaps.json"
    hub.skill_library.proposal_store.path = tmp_path / "skill_proposals.json"
    hub.skill_library.review_store.path = tmp_path / "skill_review_reports.json"
    return hub


def test_create_internal_worker_in_runtime_overrides(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Create a new internal worker named Banana Helper",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Created worker `banana_helper`" in result
    worker = hub.worker_registry.get_worker("banana_helper")
    assert worker.interface_mode == "internal"
    worker_file = tmp_path / "catalog_overrides" / "workers.json"
    assert worker_file.exists()


def test_managed_worker_request_asks_for_bot_token_then_attaches(tmp_path, monkeypatch) -> None:
    hub = build_hub(tmp_path)
    monkeypatch.setattr("agentic_hub.services.telegram.client.TelegramClient.get_me", lambda self: {"ok": True, "result": {"username": "banana_bot", "first_name": "Banana"}})
    monkeypatch.setattr("agentic_hub.services.telegram.service.TelegramPollingService.start", lambda self: setattr(self, "_running", True))

    question = hub.vanta_admin.handle_message(
        "Create a new managed telegram bot named Banana Bot",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )
    assert "What Telegram bot token" in question

    result = hub.vanta_admin.handle_message(
        "123456:banana_token",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Created worker `banana_bot`" in result
    assert "managed bot inspection succeeded" in result
    managed = hub.telegram_runtime_manager.get_managed_bot("banana_bot")
    assert managed.bot_username == "banana_bot"


def test_code_change_request_requires_approval(tmp_path) -> None:
    hub = build_hub(tmp_path)

    question = hub.vanta_admin.handle_message(
        "Make a new internal agent named Banana Painter that creates images of bananas on command",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )
    assert "What model should this worker use?" in question

    result = hub.vanta_admin.handle_message(
        "Nano-banana",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Approval required before changing executable code" in result
    assert "Banana Painter" not in [worker.name for worker in hub.worker_registry.list_workers()]


def test_plain_language_status_request_maps_to_admin_action(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "show hub status",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Hub `" in result


def test_plain_language_worker_status_request_maps_to_admin_action(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "What is the status of aria?",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Worker `aria`" in result


def test_plain_language_overview_request_lists_workers_tasks_and_services(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Inspect current hub status, workers, tasks, and services.",
        {"source": "telegram", "chat_id": 10, "user_id": 20},
    )

    assert "Hub `" in result
    assert "aria" in result
    assert "Startup Task" in result
    assert "telegram" not in result or "No services found." in result or "|" in result


def test_plain_language_worker_list_stays_read_only(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "what are the workers?",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "aria" in result
    assert "What should I call the worker?" not in result


def test_explicit_skill_request_requires_approval_before_attachment(tmp_path) -> None:
    hub = build_hub(tmp_path)

    proposal = hub.vanta_admin.handle_message(
        "Create a skill for handling banana intake requests",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Approve this skill?" in proposal
    assert "Reusable skill" in proposal

    approval = hub.vanta_admin.handle_message(
        "approve",
        {"source": "telegram", "chat_id": 1, "user_id": 2},
    )

    assert "Approved skill" in approval
    loadout = next(item for item in hub.catalog_manager.list_objects("loadouts") if item.loadout_id == "operator_core")
    assert loadout.skill_refs


def test_repeated_requests_trigger_skill_proposal(tmp_path) -> None:
    hub = build_hub(tmp_path)
    first = hub.vanta_admin.handle_message(
        "We need a consistent banana triage playbook",
        {"source": "telegram", "chat_id": 2, "user_id": 3},
    )
    second = hub.vanta_admin.handle_message(
        "We need a consistent banana triage playbook",
        {"source": "telegram", "chat_id": 2, "user_id": 3},
    )

    assert "I noted that recurring need." in first
    assert "Approve this skill?" in second


def test_create_tool_in_runtime_overrides(tmp_path) -> None:
    hub = build_hub(tmp_path)

    question = hub.vanta_admin.handle_message(
        "Create a new tool named Banana Logger",
        {"source": "telegram", "chat_id": 3, "user_id": 4},
    )
    assert "What implementation reference" in question

    result = hub.vanta_admin.handle_message(
        "agentic_hub.tools.banana.logger",
        {"source": "telegram", "chat_id": 3, "user_id": 4},
    )

    assert "Created tool `banana_logger`." in result
    assert hub.tool_registry.get("banana_logger").implementation_ref == "agentic_hub.tools.banana.logger"


def test_reminder_request_behaves_like_operator_not_capability_dump(tmp_path) -> None:
    hub = build_hub(tmp_path)

    first = hub.vanta_admin.handle_message(
        "Hey Vanta, I want to give Aria the ability to send reminders out on a schedule. What do you think?",
        {"source": "telegram", "chat_id": 11, "user_id": 12},
    )

    assert "scheduled reminders" in first.lower()
    assert "What schedule should Aria use" in first
    assert "Default capabilities:" not in first

    second = hub.vanta_admin.handle_message(
        "every monday at 9am",
        {"source": "telegram", "chat_id": 11, "user_id": 12},
    )

    assert "Where should Aria send those reminders?" in second

    third = hub.vanta_admin.handle_message(
        "to the band group chat",
        {"source": "telegram", "chat_id": 11, "user_id": 12},
    )

    assert "Approval required before changing executable code" in third
    assert "reminders" in third.lower()


def test_create_tool_low_level_path_still_works(tmp_path) -> None:
    hub = build_hub(tmp_path)

    first = hub.vanta_admin.handle_message(
        "create tool",
        {"source": "telegram", "chat_id": 21, "user_id": 22},
    )
    second = hub.vanta_admin.handle_message(
        "schedule_telegram_reminder",
        {"source": "telegram", "chat_id": 21, "user_id": 22},
    )

    assert "What should I call the tool?" in first
    assert "What implementation reference should I use for `Schedule Telegram Reminder`?" in second


def test_improve_worker_request_asks_for_outcome_not_capability_dump(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Can you make Aria better at band follow-up?",
        {"source": "telegram", "chat_id": 31, "user_id": 32},
    )

    assert "What outcome do you want most" in result
    assert "Default capabilities:" not in result


def test_default_capability_manifest_stays_compact(tmp_path) -> None:
    hub = build_hub(tmp_path)

    manifest = hub.vanta_admin.default_capabilities()

    capability_ids = {item.capability_id for item in manifest}
    assert "create_worker" in capability_ids
    assert "create_tool" in capability_ids
    assert "request_code_change" not in capability_ids
    assert all(item.escalation_pack == "default" for item in manifest)


def test_repo_capabilities_are_on_demand(tmp_path) -> None:
    hub = build_hub(tmp_path)

    manifest = hub.vanta_admin.get_capability_manifest(["default", "repo"])

    capability_ids = {item.capability_id for item in manifest}
    assert "request_code_change" in capability_ids
    assert "repo_context" in capability_ids


def test_grant_existing_tool_access_updates_worker_loadout(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Give aria access to web_search",
        {"source": "telegram", "chat_id": 8, "user_id": 9},
    )

    assert "Granted `aria` access to tool `web_search`" in result
    loadout = hub.worker_registry.get_loadout(hub.worker_registry.get_worker("aria").loadout_id)
    assert "web_search" in loadout.allowed_tool_ids


def test_grant_unknown_model_access_requests_code_change_approval(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Can we give aria the ability to access Google's nano-banana model?",
        {"source": "telegram", "chat_id": 8, "user_id": 9},
    )

    assert "Approval required before changing executable code" in result
    assert "google nano-banana" in result.lower()
