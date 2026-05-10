from __future__ import annotations

import re
from dataclasses import dataclass, field

from symkern.prompt_layer import PromptIntent, PromptValidator


@dataclass(slots=True)
class CompilerResult:
    intent: PromptIntent
    assumptions: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    confidence: float = 1.0
    translator: str = "heuristic"


class IntentCompiler:
    """Front-end compiler for human prompts.

    In v0 this exposes a pluggable, LLM-shaped boundary but uses deterministic
    heuristics so the end-to-end architecture remains runnable offline.
    """

    def __init__(self, validator: PromptValidator | None = None) -> None:
        self.validator = validator or PromptValidator()

    def compile(self, prompt: str) -> CompilerResult:
        raw_intent, translator = self._translate(prompt)
        intent = self.validator.validate(raw_intent)
        return CompilerResult(
            intent=intent,
            assumptions=intent.assumptions,
            missing_information=intent.missing_information,
            confidence=intent.confidence,
            translator=translator,
        )

    def _translate(self, prompt: str) -> tuple[PromptIntent, str]:
        text = prompt.strip()
        if not text:
            raise ValueError("Prompt cannot be empty")

        if any(marker in text for marker in ("→Ω", "Δ", "◐", "⟐")):
            return self._parse_symbolic(text), "symbolic"
        return self._heuristic_natural_language(text), "mock-llm"

    def _parse_symbolic(self, prompt: str) -> PromptIntent:
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

        return PromptIntent(
            goals=goals,
            constraints=constraints,
            preferences=preferences,
            state=state,
            sinks=sinks or ["stdout"],
            assumptions=["Symbolic prompt parsed without external translator."],
            confidence=0.92,
        )

    def _heuristic_natural_language(self, prompt: str) -> PromptIntent:
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

        return PromptIntent(
            goals=goals,
            constraints=constraints,
            preferences=preferences,
            state=state,
            sinks=sinks,
            assumptions=assumptions,
            missing_information=missing_information,
            confidence=0.78 if missing_information else 0.9,
        )

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
