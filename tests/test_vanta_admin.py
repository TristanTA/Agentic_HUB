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
    assert "What schedule should" in first
    assert "Default capabilities:" not in first

    second = hub.vanta_admin.handle_message(
        "every monday at 9am",
        {"source": "telegram", "chat_id": 11, "user_id": 12},
    )

    assert "Where should those reminders" in second

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


def test_worker_tool_question_inspects_loadout_instead_of_mutating(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "What tools does aria have access to?",
        {"source": "telegram", "chat_id": 40, "user_id": 41},
    )

    assert "inspecting the worker -> loadout -> allowed tools chain" in result.lower()
    assert "Worker `aria` uses loadout `aria_band_core`." in result
    assert "`telegram_send_message`" in result
    assert "Approval required before changing executable code" not in result


def test_cancel_clears_pending_operator_flow(tmp_path) -> None:
    hub = build_hub(tmp_path)

    first = hub.vanta_admin.handle_message(
        "Hey Vanta, I want to give Aria the ability to send reminders out on a schedule.",
        {"source": "telegram", "chat_id": 42, "user_id": 43},
    )
    cancelled = hub.vanta_admin.handle_message(
        "cancel",
        {"source": "telegram", "chat_id": 42, "user_id": 43},
    )
    fresh = hub.vanta_admin.handle_message(
        "what tools does aria have access to?",
        {"source": "telegram", "chat_id": 42, "user_id": 43},
    )

    assert "schedule" in first.lower()
    assert "Cancelled that pending flow" in cancelled
    assert "Worker `aria` uses loadout `aria_band_core`." in fresh


def test_topic_switch_starts_fresh_request_during_pending_flow(tmp_path) -> None:
    hub = build_hub(tmp_path)

    hub.vanta_admin.handle_message(
        "Create a new tool named Banana Logger",
        {"source": "telegram", "chat_id": 44, "user_id": 45},
    )
    result = hub.vanta_admin.handle_message(
        "what tools does aria have access to?",
        {"source": "telegram", "chat_id": 44, "user_id": 45},
    )

    assert "Cancelled the previous flow and started fresh." in result
    assert "Worker `aria` uses loadout `aria_band_core`." in result


def test_concise_capability_question_stays_high_level(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Can aria help with band support?",
        {"source": "telegram", "chat_id": 46, "user_id": 47},
    )

    assert "looks like something they can already handle" in result
    assert "loadout" not in result.lower()


def test_existing_tool_grant_uses_operator_preview(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Give aria access to web_search",
        {"source": "telegram", "chat_id": 48, "user_id": 49},
    )

    assert "I checked `aria`." in result
    assert "does not currently allow `web_search`" in result
    assert "Granted `aria` access to tool `web_search`" in result


def test_approval_gated_capability_request_explains_diagnosis(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Can we give aria the ability to access Google's nano-banana model?",
        {"source": "telegram", "chat_id": 50, "user_id": 51},
    )

    assert "runtime path" in result
    assert "implementation proposal" in result
    assert "Approval required before changing executable code" in result


def test_vanta_can_inspect_delegation_options(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Who can Vanta delegate to for implementation help?",
        {"source": "telegram", "chat_id": 52, "user_id": 53},
    )

    assert "Vanta can lean on these workers" in result
    assert "`forge`" in result
    assert "`nova`" in result


def test_worker_scope_follow_up_stays_helpful(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "aria can only respond on telegram? thats it?",
        {"source": "telegram", "chat_id": 60, "user_id": 61},
    )

    assert "telegram_send_message" in result
    assert "isn't just" in result.lower() or "isn't the whole picture" in result.lower() or "not the whole picture" in result.lower()
    assert "Tell me what you want to inspect or change in the hub" not in result


def test_tool_inventory_question_lists_all_tools(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "What are all the tools currently available?",
        {"source": "telegram", "chat_id": 62, "user_id": 63},
    )

    assert "telegram_send_message" in result
    assert "web_search" in result
    assert "repo_read_file" in result
    assert "Tell me what you want to inspect or change in the hub" not in result


def test_worker_mention_without_exact_route_still_uses_repo_grounded_summary(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Give me the repo-backed summary for aria",
        {"source": "telegram", "chat_id": 64, "user_id": 65},
    )

    assert "live registry and repo-backed catalog" in result
    assert "aria_band_core" in result
    assert "telegram_send_message" in result


def test_unmatched_admin_question_uses_repo_search_instead_of_generic_fallback(tmp_path) -> None:
    hub = build_hub(tmp_path)

    result = hub.vanta_admin.handle_message(
        "Where is aria's soul file defined?",
        {"source": "telegram", "chat_id": 66, "user_id": 67},
    )

    assert "worker_docs/aria/soul.md" in result or "aria.json" in result
    assert "Tell me what you want to inspect or change in the hub" not in result
