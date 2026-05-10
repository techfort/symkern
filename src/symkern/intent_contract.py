from __future__ import annotations

import json
from importlib import resources
from dataclasses import dataclass

from symkern.prompt_layer import PromptIntent, PromptValidator


SCHEMA_VERSION = "symkern.intent/v1alpha1"


def load_intent_schema() -> dict[str, object]:
    text = resources.files("symkern.resources").joinpath("intent_schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def load_intent_ontology() -> dict[str, object]:
    text = resources.files("symkern.resources").joinpath("intent_ontology.json").read_text(encoding="utf-8")
    return json.loads(text)


ONTOLOGY = load_intent_ontology()
CONSTRAINT_SYNONYMS = dict(ONTOLOGY.get("constraint_synonyms", {}))
SINK_SYNONYMS = dict(ONTOLOGY.get("sink_synonyms", {}))


@dataclass(slots=True)
class SymkernIntentContract:
    validator: PromptValidator

    def normalize(self, payload: dict[str, object]) -> PromptIntent:
        schema_version = str(payload.get("schema_version", ""))
        if schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported translator schema version: {schema_version or '<missing>'}")

        goals = self._normalize_string_list(payload.get("goals", []), field_name="goals")
        if not goals:
            raise ValueError("Translator payload must include at least one goal")

        normalized_constraints = [self._normalize_constraint(item) for item in self._normalize_string_list(payload.get("constraints", []), field_name="constraints")]
        normalized_sinks = [self._normalize_sink(item) for item in self._normalize_string_list(payload.get("sinks", []), field_name="sinks")]
        state = dict(payload.get("state", {})) if isinstance(payload.get("state", {}), dict) else {}

        return self.validator.validate(
            PromptIntent(
                goals=goals,
                constraints=[item for item in normalized_constraints if item],
                preferences=self._normalize_string_list(payload.get("preferences", []), field_name="preferences"),
                state=state,
                sinks=[item for item in normalized_sinks if item] or ["stdout"],
                assumptions=self._normalize_string_list(payload.get("assumptions", []), field_name="assumptions"),
                missing_information=self._normalize_string_list(payload.get("missing_information", []), field_name="missing_information"),
                confidence=float(payload.get("confidence", 0.0) or 0.0),
            )
        )

    @staticmethod
    def _normalize_string_list(raw_values: object, field_name: str) -> list[str]:
        values = list(raw_values) if isinstance(raw_values, list) else []
        normalized: list[str] = []
        for item in values:
            value = str(item).strip()
            if not value:
                continue
            if SymkernIntentContract._looks_like_embedded_object(value):
                raise ValueError(
                    f"Translator payload field '{field_name}' must contain plain strings, not embedded objects or serialized dictionaries"
                )
            normalized.append(value)
        return normalized

    @staticmethod
    def _looks_like_embedded_object(value: str) -> bool:
        compact = value.strip()
        if not compact:
            return False
        if (compact.startswith("{") and compact.endswith("}")) or (compact.startswith("[") and compact.endswith("]")):
            return True
        object_markers = (":'", '":', "{'", '{"', "[{")
        return any(marker in compact for marker in object_markers)

    @staticmethod
    def _normalize_constraint(value: str) -> str:
        normalized = value.strip().lower()
        return CONSTRAINT_SYNONYMS.get(normalized, normalized.replace(" ", "_"))

    @staticmethod
    def _normalize_sink(value: str) -> str:
        normalized = value.strip().lower()
        return SINK_SYNONYMS.get(normalized, normalized.replace(" ", "_"))


def build_translation_instructions() -> str:
    goal_list = ", ".join(ONTOLOGY["goals"])
    constraint_list = ", ".join(ONTOLOGY["constraints"])
    sink_list = ", ".join(ONTOLOGY["sinks"])
    schema = load_intent_schema()
    required_keys = ", ".join(list(schema.get("required", [])))
    return (
        "Translate the user request into valid Symkern intent JSON only. "
        f"Use schema_version '{SCHEMA_VERSION}'. "
        f"Allowed goals: {goal_list}. "
        f"Allowed constraints: {constraint_list}. "
        f"Allowed sinks: {sink_list}. "
        f"Return a JSON object with required keys: {required_keys}. "
        "Every list field must contain plain strings only. "
        "Do not place objects inside goals, constraints, sinks, preferences, assumptions, or missing_information. "
        "Do not serialize Python dictionaries or lists as strings. "
        "Use strict JSON with double quotes. "
        "Example: {\"schema_version\": \"symkern.intent/v1alpha1\", \"goals\": [\"generate_gaussian_array_statistics\"], \"constraints\": [], \"preferences\": [], \"state\": {\"length\": 20, \"min_value\": 0, \"max_value\": 20, \"distribution\": \"gaussian\", \"requested_statistics\": [\"standard_deviation\", \"mean\", \"median\"]}, \"sinks\": [\"artifact_store\", \"stdout\"], \"assumptions\": [], \"missing_information\": [], \"confidence\": 0.9}. "
        "Do not generate executable code. Only produce the machine intent contract."
    )