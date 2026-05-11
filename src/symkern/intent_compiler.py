from __future__ import annotations

import re
from dataclasses import dataclass, field

from symkern.intent_contract import SCHEMA_VERSION, SymkernIntentContract
from symkern.prompt_layer import ProgramSpec, ProgramSpecValidator, PromptIntent, PromptValidator
from symkern.translator import TranslationEnvelope, TranslatorAdapter


@dataclass(slots=True)
class CompilerResult:
    intent: PromptIntent
    program_spec: ProgramSpec
    assumptions: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    confidence: float = 1.0
    translator: str = "heuristic"


class IntentCompiler:
    """Front-end compiler for human prompts.

    In v0 this exposes a pluggable, LLM-shaped boundary but uses deterministic
    heuristics so the end-to-end architecture remains runnable offline.
    """

    def __init__(self, validator: PromptValidator | None = None, translator_adapter: TranslatorAdapter | None = None) -> None:
        self.validator = validator or PromptValidator()
        self.program_spec_validator = ProgramSpecValidator()
        self.contract = SymkernIntentContract(self.validator)
        self.translator_adapter = translator_adapter

    def compile(self, prompt: str) -> CompilerResult:
        raw_payload, translator = self._translate(prompt)
        try:
            intent = self.contract.normalize(raw_payload)
        except ValueError as error:
            if self.translator_adapter is None:
                raise
            repaired = self.translator_adapter.repair(prompt, raw_payload, str(error))
            raw_payload = repaired.payload
            translator = repaired.translator
            intent = self.contract.normalize(raw_payload)
        program_spec = self.program_spec_validator.validate(self._build_program_spec(prompt, intent, translator))
        return CompilerResult(
            intent=intent,
            program_spec=program_spec,
            assumptions=intent.assumptions,
            missing_information=intent.missing_information,
            confidence=intent.confidence,
            translator=translator,
        )

    def _build_program_spec(self, prompt: str, intent: PromptIntent, translator: str) -> ProgramSpec:
        requested_inputs, requested_outputs, transformations, synthesis_gaps = self._program_shape_for_intent(prompt, intent)
        synthesis_gaps.extend(self._prompt_fidelity_gaps(prompt, intent))
        return ProgramSpec(
            program_id=self._slugify(intent.goals[0]),
            title=prompt.strip(),
            requested_inputs=requested_inputs,
            requested_outputs=requested_outputs,
            transformations=transformations,
            hard_constraints=list(intent.constraints),
            preferences=list(intent.preferences),
            state_bindings=dict(intent.state),
            assumptions=list(intent.assumptions),
            missing_information=list(intent.missing_information),
            synthesis_gaps=synthesis_gaps,
            translator_metadata={"translator": translator, "source": "prompt"},
            confidence=intent.confidence,
        )

    def _prompt_fidelity_gaps(self, prompt: str, intent: PromptIntent) -> list[dict[str, object]]:
        text = prompt.strip()
        if not text or any(marker in text for marker in ("→Ω", "Δ", "◐", "⟐")):
            return []
        if self._prompt_supports_goal(text, intent.goals):
            return []
        return [
            {
                "gap_id": "gap-translator-goal-mismatch",
                "stage_id": "translator_alignment",
                "reason": "translator_goal_mismatch",
                "severity": "blocking",
                "requested_capability": text,
                "notes": f"Translator selected goal family {intent.goals[0]!r}, but the original prompt does not provide enough evidence for that family.",
            }
        ]

    @staticmethod
    def _prompt_supports_goal(prompt: str, goals: list[str]) -> bool:
        lower = prompt.lower()
        if goals == ["detect_stream_anomalies"]:
            return any(token in lower for token in ("anomaly", "anomalies", "outlier", "outliers"))
        if goals == ["elect_illustrious_historical_death"]:
            return all(token in lower for token in ("historical dates", "wikipedia", "deaths", "illustrious"))
        if goals == ["generate_gaussian_array_statistics"]:
            return (
                "array" in lower
                and ("gaussian" in lower or "normal distribution" in lower)
                and any(token in lower for token in ("standard deviation", "std deviation", "mean", "median"))
            )
        if goals == ["generate_random_mapped_array"]:
            return all(token in lower for token in ("array", "random", "map"))
        return False

    def _program_shape_for_intent(
        self,
        prompt: str,
        intent: PromptIntent,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
        if intent.goals == ["detect_stream_anomalies"]:
            return (
                [
                    {
                        "name": "events",
                        "kind": "event_stream",
                        "required": False,
                        "source": "invoke-time",
                    }
                ],
                [{"name": "detections", "kind": "array[event_detection]"}],
                [
                    {
                        "stage_id": "window_events",
                        "kind": "stream_window",
                        "description": "Partition the input stream into rolling windows.",
                        "inputs": ["events"],
                        "outputs": ["windowed_events"],
                        "blocking": True,
                    },
                    {
                        "stage_id": "score_anomalies",
                        "kind": "anomaly_scoring",
                        "description": "Establish a baseline, score deviations, and compare scores to a threshold.",
                        "inputs": ["windowed_events"],
                        "outputs": ["detections"],
                        "blocking": True,
                    },
                ],
                [],
            )
        if intent.goals == ["generate_random_mapped_array"]:
            return (
                [
                    {
                        "name": "source_array",
                        "kind": "array[integer]",
                        "required": False,
                        "source": "invoke-time",
                        "constraints": {
                            "expected_length": int(intent.state.get("length", 5)),
                            "min_value": int(intent.state.get("min_value", 1)),
                            "max_value": int(intent.state.get("max_value", 10)),
                        },
                    }
                ],
                [
                    {"name": "source_array", "kind": "array[integer]"},
                    {"name": "mapped_array", "kind": "array[integer]"},
                    {"name": "operations", "kind": "array[string]"},
                ],
                [
                    {
                        "stage_id": "obtain_source_array",
                        "kind": "array_source",
                        "description": "Accept an external integer array or synthesize one within the configured bounds.",
                        "inputs": [],
                        "outputs": ["source_array"],
                        "blocking": True,
                    },
                    {
                        "stage_id": "map_array",
                        "kind": "array_transformation",
                        "description": "Apply randomized arithmetic operations to each member of the source array.",
                        "inputs": ["source_array"],
                        "outputs": ["mapped_array", "operations"],
                        "blocking": True,
                    },
                ],
                [],
            )
        if intent.goals == ["generate_gaussian_array_statistics"]:
            return (
                [
                    {
                        "name": "source_array",
                        "kind": "array[number]",
                        "required": False,
                        "source": "invoke-time",
                        "constraints": {
                            "expected_length": int(intent.state.get("length", 20)),
                            "min_value": float(intent.state.get("min_value", 0)),
                            "max_value": float(intent.state.get("max_value", 20)),
                        },
                    }
                ],
                [
                    {"name": "source_array", "kind": "array[number]"},
                    {"name": "statistics", "kind": "object[array_statistics]"},
                ],
                [
                    {
                        "stage_id": "obtain_source_array",
                        "kind": "array_source",
                        "description": "Accept an external numeric array or synthesize a bounded gaussian-distributed one.",
                        "inputs": [],
                        "outputs": ["source_array"],
                        "blocking": True,
                    },
                    {
                        "stage_id": "compute_statistics",
                        "kind": "array_analytics",
                        "description": "Compute summary statistics over the numeric array.",
                        "inputs": ["source_array"],
                        "outputs": ["statistics"],
                        "blocking": True,
                    },
                ],
                [],
            )
        if intent.goals == ["elect_illustrious_historical_death"]:
            return (
                [
                    {
                        "name": "historical_dates",
                        "kind": "array[historical_date]",
                        "required": False,
                        "source": "invoke-time",
                        "constraints": {"expected_length": int(intent.state.get("date_count", 3))},
                    }
                ],
                [
                    {"name": "historical_dates", "kind": "array[historical_date]"},
                    {"name": "death_candidates", "kind": "array[death_candidate]"},
                    {"name": "selected_death", "kind": "object[death_candidate]"},
                ],
                [
                    {
                        "stage_id": "obtain_dates",
                        "kind": "date_source",
                        "description": "Accept historical dates or synthesize candidate dates for lookup.",
                        "inputs": [],
                        "outputs": ["historical_dates"],
                        "blocking": True,
                    },
                    {
                        "stage_id": "lookup_deaths",
                        "kind": "external_lookup",
                        "description": "Retrieve death candidates for the selected dates from Wikipedia.",
                        "inputs": ["historical_dates"],
                        "outputs": ["death_candidates", "death_candidate_features"],
                        "blocking": True,
                    },
                    {
                        "stage_id": "select_candidate",
                        "kind": "decision",
                        "description": "Select the most illustrious death candidate from derived features.",
                        "inputs": ["death_candidate_features"],
                        "outputs": ["selected_death"],
                        "blocking": True,
                    },
                ],
                [],
            )
        return (
            [],
            [{"name": "emitted", "kind": "object[generic_result]"}],
            [
                {
                    "stage_id": "unresolved_request",
                    "kind": "unresolved_goal",
                    "description": prompt.strip(),
                    "inputs": [],
                    "outputs": ["emitted"],
                    "blocking": True,
                }
            ],
            [
                {
                    "gap_id": "gap-unsupported-goal",
                    "stage_id": "unresolved_request",
                    "reason": "unsupported_goal_family",
                    "severity": "blocking",
                    "requested_capability": intent.goals[0],
                    "notes": "No validated open-ended planner exists yet for this request.",
                }
            ],
        )

    @staticmethod
    def _slugify(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return normalized or "program"

    def _translate(self, prompt: str) -> tuple[dict[str, object], str]:
        text = prompt.strip()
        if not text:
            raise ValueError("Prompt cannot be empty")

        if self.translator_adapter is not None:
            translated = self.translator_adapter.translate(text)
            return translated.payload, translated.translator
        if any(marker in text for marker in ("→Ω", "Δ", "◐", "⟐")):
            return self._parse_symbolic(text), "symbolic"
        return self._heuristic_natural_language(text), "mock-llm"

    def _parse_symbolic(self, prompt: str) -> dict[str, object]:
        goals: list[str] = []
        constraints: list[str] = []
        sinks: list[str] = []
        state: dict[str, object] = {}
        preferences: list[str] = []

        for raw_line in prompt.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("→Ω"):
                goals.append(line.removeprefix("→Ω").strip(" :"))
            elif line.startswith("Δ"):
                constraints.append(line.removeprefix("Δ").strip(" :"))
            elif line.startswith("⟐"):
                sinks.append(line.removeprefix("⟐").strip(" :"))
            elif line.startswith("◐"):
                payload = line.removeprefix("◐").strip(" :")
                key, _, value = payload.partition("=")
                if key:
                    state[key.strip()] = value.strip() if value else payload
            else:
                preferences.append(line)

        return {
            "schema_version": SCHEMA_VERSION,
            "goals": goals,
            "constraints": constraints,
            "preferences": preferences,
            "state": state,
            "sinks": sinks or ["stdout"],
            "assumptions": ["Symbolic prompt parsed without external translator."],
            "missing_information": [],
            "confidence": 0.92,
        }

    def _heuristic_natural_language(self, prompt: str) -> dict[str, object]:
        lower = prompt.lower()
        constraints: list[str] = []
        preferences: list[str] = []
        assumptions = ["Natural-language prompt was normalized through the mock LLM compiler."]
        missing_information: list[str] = []
        state: dict[str, object] = {}
        sinks = ["artifact_store", "stdout"]

        if "low false positive" in lower or "false positives" in lower:
            constraints.append("minimize_false_positives")
        if "latency" in lower or "real-time" in lower or "stream" in lower:
            constraints.append("low_latency")
        if "parallel" in lower or "bulk" in lower:
            preferences.append("bulk_execution")

        if any(token in lower for token in ("anomaly", "anomalies", "outlier", "outliers")):
            goals = ["detect_stream_anomalies"]
            state["domain"] = "stream_anomaly_detection"
            state["window_size"] = 5
        elif all(token in lower for token in ("historical dates", "wikipedia", "deaths", "illustrious")):
            goals = ["elect_illustrious_historical_death"]
            state.update(self._extract_historical_death_state(lower))
            state["domain"] = "historical_wikipedia_lookup"
            assumptions.append("Wikipedia on-this-day death entries are used as the source of candidate deaths.")
        elif "array" in lower and ("gaussian" in lower or "normal distribution" in lower) and any(
            token in lower for token in ("standard deviation", "std deviation", "mean", "median")
        ):
            goals = ["generate_gaussian_array_statistics"]
            state.update(self._extract_gaussian_statistics_state(lower))
            state["domain"] = "array_statistics"
            assumptions.append("Standard deviation is interpreted as population standard deviation for the generated array.")
        elif all(token in lower for token in ("array", "random", "map")):
            goals = ["generate_random_mapped_array"]
            state.update(self._extract_array_generation_state(lower))
            state["domain"] = "array_transformation"
        else:
            goals = [prompt.rstrip(".")]
            missing_information.append("No domain-specific planner matched the prompt; using generic plan synthesis.")

        return {
            "schema_version": SCHEMA_VERSION,
            "goals": goals,
            "constraints": constraints,
            "preferences": preferences,
            "state": state,
            "sinks": sinks,
            "assumptions": assumptions,
            "missing_information": missing_information,
            "confidence": 0.78 if missing_information else 0.9,
        }

    @staticmethod
    def _extract_array_generation_state(prompt: str) -> dict[str, object]:
        length = 5
        min_value = 1
        max_value = 10

        length_match = re.search(r"(\d+)[- ]element", prompt)
        if not length_match:
            length_match = re.search(r"array\s+of\s+(\d+)\s+numbers", prompt)
        if length_match:
            length = int(length_match.group(1))

        range_match = re.search(r"between\s+(\d+)\s*(?:and|-)\s*(\d+)", prompt)
        if range_match:
            min_value = int(range_match.group(1))
            max_value = int(range_match.group(2))

        return {
            "length": length,
            "min_value": min_value,
            "max_value": max_value,
            "operation_pool": ["add", "subtract", "multiply"],
        }

    @staticmethod
    def _extract_gaussian_statistics_state(prompt: str) -> dict[str, object]:
        base = IntentCompiler._extract_array_generation_state(prompt)
        return {
            "length": int(base["length"]),
            "min_value": int(base["min_value"]),
            "max_value": int(base["max_value"]),
            "distribution": "gaussian",
            "requested_statistics": ["standard_deviation", "mean", "median"],
        }

    @staticmethod
    def _extract_historical_death_state(prompt: str) -> dict[str, object]:
        count = 3
        count_match = re.search(r"(\d+)\s+historical\s+dates", prompt)
        if count_match:
            count = int(count_match.group(1))
        return {
            "date_count": count,
            "lookup_source": "wikipedia.org",
            "selection_goal": "most_illustrious_death",
        }
