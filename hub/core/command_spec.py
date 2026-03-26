from __future__ import annotations


OBJECT_KINDS = ["workers", "worker_roles", "worker_types", "tools", "loadouts", "tasks"]

KIND_LABELS = {
    "workers": "worker",
    "worker_roles": "role",
    "worker_types": "worker type",
    "tools": "tool",
    "loadouts": "loadout",
    "tasks": "task",
}

EDITABLE_FIELDS = {
    "workers": ["name", "type_id", "role_id", "loadout_id", "enabled", "priority_bias", "owner", "notes"],
    "worker_roles": ["name", "purpose", "behavior_guide_ref", "default_output_style"],
    "worker_types": ["name", "execution_mode", "can_use_tools", "can_spawn_tasks", "can_request_approval", "allowed_task_kinds"],
    "tools": ["name", "description", "implementation_ref", "enabled", "safety_level", "capability_tags"],
    "loadouts": ["name", "description", "memory_policy_ref", "allowed_tool_ids", "tool_policy_overrides", "tags"],
    "tasks": ["name", "handler_name", "priority", "enabled", "trigger", "interval_seconds", "payload"],
}

CREATE_FIELDS = {
    "workers": ["name", "type_id", "role_id", "loadout_id", "enabled"],
    "worker_roles": ["name", "purpose", "behavior_guide_ref", "default_output_style"],
    "worker_types": ["name", "execution_mode", "can_use_tools", "can_spawn_tasks", "can_request_approval", "allowed_task_kinds"],
    "tools": ["name", "description", "implementation_ref", "safety_level", "enabled", "capability_tags"],
    "loadouts": ["name", "memory_policy_ref", "allowed_tool_ids", "tool_policy_overrides", "tags"],
    "tasks": ["name", "handler_name", "priority", "trigger", "interval_seconds", "enabled", "payload"],
}

FIELD_HINTS = {
    "enabled": "Answer yes or no.",
    "can_use_tools": "Answer yes or no.",
    "can_spawn_tasks": "Answer yes or no.",
    "can_request_approval": "Answer yes or no.",
    "priority_bias": "Enter an integer.",
    "priority": "Enter an integer.",
    "interval_seconds": "Enter an integer or blank.",
    "allowed_task_kinds": "Enter JSON list, for example [\"message\", \"research\"].",
    "allowed_tool_ids": "Enter JSON list of tool IDs.",
    "capability_tags": "Enter JSON list of tags.",
    "tool_policy_overrides": "Enter JSON object of tool policy overrides.",
    "payload": "Enter JSON object.",
    "tags": "Enter JSON list of tags.",
}

CHOICE_SOURCES = {
    "type_id": "worker_types",
    "role_id": "worker_roles",
    "loadout_id": "loadouts",
    "memory_policy_ref": "memory_policies",
    "safety_level": ["low", "medium", "high"],
    "execution_mode": ["llm", "deterministic", "approval"],
    "trigger": ["startup", "interval", "once", "manual"],
}
