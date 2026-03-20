from __future__ import annotations

from shared.schemas import MatchType, NormalizedEvent, RouteDecision, RoutingRule


class DeterministicRouter:
    def __init__(self, rules: list[RoutingRule], config_version: str = "v1") -> None:
        self.rules = rules
        self.config_version = config_version

    def route(self, event: NormalizedEvent) -> RouteDecision:
        text = event.text.lower()
        fallback_rule: RoutingRule | None = None
        for rule in self.rules:
            if rule.match.type == MatchType.FALLBACK:
                fallback_rule = rule
                continue
            if rule.match.type == MatchType.CONTAINS_ANY and any(token.lower() in text for token in rule.match.values):
                return RouteDecision(
                    matched_rule=rule.id,
                    target_type=rule.target_type,
                    target_id=rule.target_id,
                    reason=rule.reason,
                    config_version=self.config_version,
                )
        if fallback_rule is None:
            raise ValueError("No fallback route configured")
        return RouteDecision(
            matched_rule=fallback_rule.id,
            target_type=fallback_rule.target_type,
            target_id=fallback_rule.target_id,
            reason=fallback_rule.reason,
            config_version=self.config_version,
        )
