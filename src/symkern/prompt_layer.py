from __future__ import annotations

from dataclasses import dataclass, field


PROGRAM_SPEC_VERSION = "symkern.program-spec/v1alpha1"


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


@dataclass(slots=True)
class ProgramSpec:
    requested_inputs: list[dict[str, object]]
    requested_outputs: list[dict[str, object]]
    transformations: list[dict[str, object]]
    program_id: str | None = None
    title: str | None = None
    hard_constraints: list[str] = field(default_factory=list)
    soft_constraints: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    state_bindings: dict[str, object] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    synthesis_gaps: list[dict[str, object]] = field(default_factory=list)
    translator_metadata: dict[str, object] = field(default_factory=dict)
    confidence: float = 1.0
    spec_version: str = PROGRAM_SPEC_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "spec_version": self.spec_version,
            "program_id": self.program_id,
            "title": self.title,
            "requested_inputs": [dict(item) for item in self.requested_inputs],
            "requested_outputs": [dict(item) for item in self.requested_outputs],
            "transformations": [dict(item) for item in self.transformations],
            "hard_constraints": list(self.hard_constraints),
            "soft_constraints": list(self.soft_constraints),
            "preferences": list(self.preferences),
            "state_bindings": dict(self.state_bindings),
            "assumptions": list(self.assumptions),
            "missing_information": list(self.missing_information),
            "synthesis_gaps": [dict(item) for item in self.synthesis_gaps],
            "translator_metadata": dict(self.translator_metadata),
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "ProgramSpec":
        return cls(
            spec_version=str(payload.get("spec_version", PROGRAM_SPEC_VERSION)),
            program_id=str(payload.get("program_id", "")).strip() or None,
            title=str(payload.get("title", "")).strip() or None,
            requested_inputs=[cls._coerce_named_item(item) for item in list(payload.get("requested_inputs", []))],
            requested_outputs=[cls._coerce_named_item(item) for item in list(payload.get("requested_outputs", []))],
            transformations=[cls._coerce_transformation(item) for item in list(payload.get("transformations", []))],
            hard_constraints=[str(item) for item in list(payload.get("hard_constraints", []))],
            soft_constraints=[str(item) for item in list(payload.get("soft_constraints", []))],
            preferences=[str(item) for item in list(payload.get("preferences", []))],
            state_bindings=dict(payload.get("state_bindings", {})) if isinstance(payload.get("state_bindings", {}), dict) else {},
            assumptions=[str(item) for item in list(payload.get("assumptions", []))],
            missing_information=[str(item) for item in list(payload.get("missing_information", []))],
            synthesis_gaps=[dict(item) for item in list(payload.get("synthesis_gaps", []))],
            translator_metadata=dict(payload.get("translator_metadata", {})) if isinstance(payload.get("translator_metadata", {}), dict) else {},
            confidence=float(payload.get("confidence", 0.0) or 0.0),
        )

    @staticmethod
    def _coerce_named_item(item: object) -> dict[str, object]:
        if isinstance(item, dict):
            return dict(item)
        return {"name": str(item)}

    @classmethod
    def _coerce_transformation(cls, item: object) -> dict[str, object]:
        if isinstance(item, dict):
            normalized = dict(item)
        else:
            normalized = {"kind": str(item)}
        if "inputs" in normalized and isinstance(normalized["inputs"], list):
            normalized["inputs"] = [cls._coerce_named_item(value) for value in list(normalized["inputs"])]
        if "outputs" in normalized and isinstance(normalized["outputs"], list):
            normalized["outputs"] = [cls._coerce_named_item(value) for value in list(normalized["outputs"])]
        return normalized


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


class ProgramSpecValidator:
    """Deterministically validate the machine-checkable program creation contract."""

    def validate(self, spec: ProgramSpec) -> ProgramSpec:
        if spec.spec_version != PROGRAM_SPEC_VERSION:
            raise ValueError(f"Unsupported ProgramSpec version: {spec.spec_version}")
        if not spec.requested_outputs:
            raise ValueError("ProgramSpec requires at least one requested output")
        if not spec.transformations:
            raise ValueError("ProgramSpec requires at least one transformation")

        return ProgramSpec(
            spec_version=spec.spec_version,
            program_id=spec.program_id.strip() if isinstance(spec.program_id, str) and spec.program_id.strip() else None,
            title=spec.title.strip() if isinstance(spec.title, str) and spec.title.strip() else None,
            requested_inputs=[self._normalize_input(item) for item in spec.requested_inputs],
            requested_outputs=[self._normalize_output(item) for item in spec.requested_outputs],
            transformations=[self._normalize_transformation(item) for item in spec.transformations],
            hard_constraints=PromptValidator._dedupe(spec.hard_constraints),
            soft_constraints=PromptValidator._dedupe(spec.soft_constraints),
            preferences=PromptValidator._dedupe(spec.preferences),
            state_bindings=dict(spec.state_bindings),
            assumptions=PromptValidator._dedupe(spec.assumptions),
            missing_information=PromptValidator._dedupe(spec.missing_information),
            synthesis_gaps=[dict(item) for item in spec.synthesis_gaps],
            translator_metadata=dict(spec.translator_metadata),
            confidence=min(1.0, max(0.0, spec.confidence)),
        )

    @staticmethod
    def _normalize_input(item: dict[str, object]) -> dict[str, object]:
        normalized = dict(item)
        normalized["name"] = str(normalized.get("name", "")).strip()
        if not normalized["name"]:
            raise ValueError("ProgramSpec requested_inputs entries require a name")
        normalized.setdefault("kind", "opaque")
        normalized.setdefault("required", True)
        normalized.setdefault("source", "invoke-time")
        return normalized

    @staticmethod
    def _normalize_output(item: dict[str, object]) -> dict[str, object]:
        normalized = dict(item)
        normalized["name"] = str(normalized.get("name", "")).strip()
        if not normalized["name"]:
            raise ValueError("ProgramSpec requested_outputs entries require a name")
        normalized.setdefault("kind", "opaque")
        return normalized

    @staticmethod
    def _normalize_transformation(item: dict[str, object]) -> dict[str, object]:
        normalized = dict(item)
        if "operator" in normalized and "operator_id" not in normalized:
            normalized["operator_id"] = normalized.get("operator")
        if "outputs" in normalized:
            normalized["outputs"] = [
                (dict(output) if isinstance(output, dict) else {"name": str(output)})
                for output in list(normalized.get("outputs", []))
            ]
        if "inputs" in normalized:
            normalized["inputs"] = [
                (dict(input_item) if isinstance(input_item, dict) else {"name": str(input_item)})
                for input_item in list(normalized.get("inputs", []))
            ]
        return normalized
