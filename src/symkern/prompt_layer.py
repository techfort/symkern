from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class PromptIntent:
    goals: list[str]
    constraints: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    state: dict[str, object] = field(default_factory=dict)
    sinks: list[str] = field(default_factory=lambda: ["stdout"])
    assumptions: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    confidence: float = 1.0


class PromptValidator:
    """Deterministically normalize machine-consumable prompt intents."""

    def validate(self, intent: PromptIntent) -> PromptIntent:
        goals = [goal.strip() for goal in intent.goals if goal.strip()]
        if not goals:
            raise ValueError("PromptIntent requires at least one goal")

        constraints = self._dedupe(intent.constraints)
        preferences = self._dedupe(intent.preferences)
        sinks = self._dedupe(intent.sinks) or ["stdout"]
        assumptions = self._dedupe(intent.assumptions)
        missing_information = self._dedupe(intent.missing_information)
        confidence = min(1.0, max(0.0, intent.confidence))

        return PromptIntent(
            goals=goals,
            constraints=constraints,
            preferences=preferences,
            state=dict(intent.state),
            sinks=sinks,
            assumptions=assumptions,
            missing_information=missing_information,
            confidence=confidence,
        )

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result
