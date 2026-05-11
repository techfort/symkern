from __future__ import annotations

from dataclasses import dataclass
from reprlib import repr as limited_repr

from symkern.artifacts import ArtifactBundle


@dataclass(slots=True)
class PeriscopeReport:
    summary: str
    details: str

    def render(self) -> str:
        return f"# Periscope\n\n{self.summary}\n\n{self.details}\n"


class Periscope:
    def explain(self, bundle: ArtifactBundle) -> PeriscopeReport:
        operation_schemas = {
            int(op_code): dict(descriptor)
            for op_code, descriptor in dict(bundle.language_snapshot.get("operation_schemas", {})).items()
        }
        invented = ", ".join(self._format_invention(item, operation_schemas) for item in bundle.inventions) or "none"
        detections = bundle.outputs.get("emitted", {}).get("detections", []) if isinstance(bundle.outputs.get("emitted"), dict) else []
        summary = (
            f"Run `{bundle.run_id}` converged with status `{bundle.status}`. "
            f"The machine artifact contains {len(bundle.plan.nodes)} nodes and invented abstractions: {invented}."
        )
        input_lines = self._describe_inputs(bundle, operation_schemas)
        output_lines = self._describe_outputs(bundle)
        strategy_lines = self._reconstruct_strategy(bundle, operation_schemas)
        narrative_lines = self._infer_machine_narratives(bundle, operation_schemas)
        abstraction_lines = self._describe_abstractions(bundle.inventions, operation_schemas)
        details = "\n".join(
            [
                "## What The Artifact Does",
                f"- Goals: {', '.join(bundle.plan.metadata.get('goals', []))}",
                f"- Strategy: {bundle.plan.metadata.get('strategy', 'unknown')}",
                f"- Final detections: {detections}",
                f"- Reason codes: {', '.join(bundle.reason_codes) or 'none'}",
                "## Synthesis Validation",
                *self._describe_synthesis_validation(bundle),
                "## Inputs",
                *input_lines,
                "## Outputs",
                *output_lines,
                "## Backend Selection",
                *self._describe_backend(bundle),
                "## Performance",
                *self._describe_performance(bundle),
                "## Reconstructed Strategy",
                *strategy_lines,
                "## Machine Intent Narrative",
                *narrative_lines,
                "## Machine Abstractions",
                *abstraction_lines,
                "## Execution Trace",
                *[f"- [{event.stage}] {event.message}" for event in bundle.trace.events],
            ]
        )
        return PeriscopeReport(summary=summary, details=details)

    @staticmethod
    def _describe_synthesis_validation(bundle: ArtifactBundle) -> list[str]:
        validation = dict(bundle.synthesis_validation)
        if not validation:
            gaps = list(dict(bundle.program_spec).get("synthesis_gaps", []))
            if not gaps:
                return ["- No synthesis validation details were recorded for this run."]
            return [
                "- Validation details were not persisted separately, but the program spec contains synthesis gaps.",
                *[
                    f"- Gap `{gap.get('reason', 'unknown')}` at stage `{gap.get('stage_id', 'unknown')}`: {gap.get('notes', 'none')}"
                    for gap in gaps
                ],
            ]
        lines = [f"- Status: {validation.get('status', 'unknown')}"]
        for failure in list(validation.get("failures", [])):
            lines.append(
                f"- Failure `{failure.get('reason', 'unknown')}` at stage `{failure.get('stage_id', 'unknown')}`: {failure.get('notes', 'none')}"
            )
        if not list(validation.get("failures", [])):
            lines.append("- No synthesis failures were recorded.")
        return lines

    @staticmethod
    def _reconstruct_strategy(bundle: ArtifactBundle, operation_schemas: dict[int, dict[str, object]]) -> list[str]:
        nodes = bundle.plan.ordered_nodes()
        if not nodes:
            return ["- No executable strategy was synthesized."]

        stages: list[str] = []
        current_category = None
        current_codes: list[int] = []
        for node in nodes:
            descriptor = operation_schemas.get(node.op_code or -1, {})
            category = str(descriptor.get("machine_metadata", {}).get("category", "opaque"))
            if category != current_category and current_codes:
                stages.append(Periscope._format_stage(current_category or "opaque", current_codes, operation_schemas))
                current_codes = []
            current_category = category
            if node.op_code is not None:
                current_codes.append(node.op_code)
        if current_codes:
            stages.append(Periscope._format_stage(current_category or "opaque", current_codes, operation_schemas))

        outputs = ", ".join(bundle.outputs.keys()) or "no materialized outputs"
        return [
            f"- The machine resolves the goal through {len(stages)} execution stages.",
            *stages,
            f"- The resulting output surface is {outputs}.",
        ]

    @staticmethod
    def _describe_inputs(bundle: ArtifactBundle, operation_schemas: dict[int, dict[str, object]]) -> list[str]:
        produced_symbols = {
            output
            for node in bundle.plan.ordered_nodes()
            for output in node.outputs
        }
        external_inputs: list[str] = []
        for node in bundle.plan.ordered_nodes():
            descriptor = operation_schemas.get(node.op_code or -1, {})
            signature = dict(descriptor.get("signature", {}))
            candidate_inputs = list(node.inputs) or list(signature.get("inputs", []))
            for symbol in candidate_inputs:
                if symbol not in produced_symbols and symbol not in external_inputs:
                    external_inputs.append(symbol)

        synthesized_inputs: list[str] = []
        for node in bundle.plan.ordered_nodes():
            descriptor = operation_schemas.get(node.op_code or -1, {})
            signature = dict(descriptor.get("signature", {}))
            if list(signature.get("inputs", [])):
                continue
            for symbol in node.outputs:
                if symbol in bundle.outputs and symbol not in synthesized_inputs:
                    synthesized_inputs.append(symbol)

        lines: list[str] = []
        if external_inputs:
            lines.extend(f"- Passed input `{symbol}` enters from outside the machine plan." for symbol in external_inputs)
        if synthesized_inputs:
            lines.extend(
                f"- Synthesized input `{symbol}` was created inside the plan before downstream use."
                for symbol in synthesized_inputs
            )
        if not lines:
            lines.append("- No explicit passed or synthesized inputs were surfaced for this run.")
        return lines

    @staticmethod
    def _describe_outputs(bundle: ArtifactBundle) -> list[str]:
        if not bundle.outputs:
            return ["- No materialized outputs were produced."]

        lines = []
        for name, value in bundle.outputs.items():
            lines.append(f"- Output `{name}` = {limited_repr(value)}")
        return lines

    @staticmethod
    def _describe_backend(bundle: ArtifactBundle) -> list[str]:
        backend = dict(bundle.backend)
        selection = dict(backend.get("selection", {}))
        candidates = list(backend.get("candidates", []))
        artifacts = dict(backend.get("artifacts", {}))
        if not selection and not candidates:
            return ["- No compiled backend candidates were considered for this run."]

        lines: list[str] = []
        if selection:
            lines.append(
                f"- Selected backend `{selection.get('target', 'unknown')}` for slice {', '.join(selection.get('slice_node_ids', [])) or 'none'}."
            )
            lines.append(
                f"- Estimated interpreted cost: {Periscope._format_ns(int(selection.get('estimated_interpreted_ns', 0)))}; estimated compiled cost: {Periscope._format_ns(int(selection.get('estimated_compiled_ns', 0)))}."
            )
            lines.append(f"- Selection reason: {selection.get('selection_reason', 'none')}" )
        if candidates:
            lines.append(
                "- Candidate backends: "
                + "; ".join(
                    f"{item.get('target', 'unknown')}[{', '.join(item.get('slice_node_ids', []))}]"
                    for item in candidates
                )
            )
        if artifacts:
            lines.extend(f"- Backend artifact `{name}` saved to `{path}`." for name, path in artifacts.items())
        return lines

    @staticmethod
    def _describe_performance(bundle: ArtifactBundle) -> list[str]:
        if not bundle.timings:
            return ["- No timing metrics were recorded for this run."]

        lines: list[str] = []
        node_timings = dict(bundle.timings.get("node_execute_ns", {}))
        for key, value in bundle.timings.items():
            if key == "node_execute_ns":
                continue
            if isinstance(value, int):
                lines.append(f"- {key}: {Periscope._format_ns(value)}")

        if node_timings:
            lines.append(
                "- Per-node execution: "
                + ", ".join(f"{node_id}={Periscope._format_ns(int(duration_ns))}" for node_id, duration_ns in node_timings.items())
            )
        return lines or ["- No timing metrics were recorded for this run."]

    @staticmethod
    def _format_ns(duration_ns: int) -> str:
        return f"{duration_ns / 1_000_000:.3f} ms"

    @staticmethod
    def _format_stage(category: str, op_codes: list[int], operation_schemas: dict[int, dict[str, object]]) -> str:
        stage_roles = []
        for op_code in op_codes:
            descriptor = operation_schemas.get(op_code, {})
            signature = dict(descriptor.get("signature", {}))
            inputs = ", ".join(signature.get("inputs", [])) or "machine state"
            outputs = ", ".join(signature.get("outputs", [])) or "machine state"
            stage_roles.append(f"opcode {op_code} transforms {inputs} into {outputs}")
        summarized = "; ".join(stage_roles)
        return f"- Stage `{category}` uses {summarized}."

    @staticmethod
    def _describe_abstractions(inventions: list[dict[str, object]], operation_schemas: dict[int, dict[str, object]]) -> list[str]:
        if not inventions:
            return ["- No invented abstractions were needed for this run."]

        lines = []
        for invention in inventions:
            op_code = int(invention.get("op_code", -1))
            descriptor = operation_schemas.get(op_code, {})
            description = str(descriptor.get("description", invention.get("rationale", "opaque invented abstraction")))
            source_codes = ", ".join(str(code) for code in list(invention.get("source_op_codes", []))) or "none"
            lines.append(
                f"- Opcode {op_code} compresses source opcodes {source_codes}. Purpose: {description}"
            )
        return lines

    @staticmethod
    def _infer_machine_narratives(bundle: ArtifactBundle, operation_schemas: dict[int, dict[str, object]]) -> list[str]:
        goals = list(bundle.plan.metadata.get("goals", []))
        strategy = str(bundle.plan.metadata.get("strategy", "unknown"))
        opcodes = [node.op_code for node in bundle.plan.ordered_nodes() if node.op_code is not None]
        invention_codes = {int(invention.get("op_code", -1)) for invention in bundle.inventions}
        categories = [
            str(operation_schemas.get(op_code, {}).get("machine_metadata", {}).get("category", "opaque"))
            for op_code in opcodes
        ]
        outputs = set(bundle.outputs.keys())
        narratives: list[str] = []

        if Periscope._looks_like_anomaly_family(categories, outputs):
            thresholds = [
                float(node.metadata.get("threshold", 0.0))
                for node in bundle.plan.nodes
                if "threshold" in node.metadata
            ]
            if strategy == "conservative" or any(threshold >= 2.4 for threshold in thresholds):
                narratives.append(
                    "- The machine chose a conservative anomaly envelope, raising the detection boundary before committing results."
                )
            else:
                narratives.append(
                    "- The machine chose a faster anomaly envelope, prioritizing responsiveness over additional filtering margin."
                )
            if invention_codes:
                narratives.append(
                    "- The machine fused scoring and threshold comparison into a reusable anomaly abstraction to reduce intermediate decision state."
                )

        if Periscope._looks_like_array_family(outputs, categories):
            if invention_codes:
                narratives.append(
                    "- The machine fused array synthesis and transformation so generation and randomized mapping can be treated as one reusable production step."
                )
            else:
                narratives.append(
                    "- The machine kept array synthesis and transformation separate, preserving an explicit intermediate array for downstream reuse."
                )

        if 105 in opcodes:
            narratives.append(
                "- The machine terminates by materializing a sink-facing output surface rather than exposing its internal execution form."
            )

        if not narratives:
            narratives.append(
                "- The machine composed an opaque opcode sequence and exposed only the output surface needed to satisfy the goal."
            )
        return narratives

    @staticmethod
    def _looks_like_anomaly_family(categories: list[str], outputs: set[str]) -> bool:
        return "stream" in categories and ("detections" in outputs or "emitted" in outputs)

    @staticmethod
    def _looks_like_array_family(outputs: set[str], categories: list[str]) -> bool:
        return "array" in categories and ({"source_array", "mapped_array"} & outputs) != set()

    @staticmethod
    def _format_invention(invention: dict[str, object], operation_schemas: dict[int, dict[str, object]]) -> str:
        op_code = int(invention.get("op_code", -1))
        descriptor = operation_schemas.get(op_code, {})
        description = str(descriptor.get("description", invention.get("rationale", "opaque invented abstraction")))
        return f"opcode {op_code} ({description})"
