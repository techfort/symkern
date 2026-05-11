from __future__ import annotations

import json
import random
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, pstdev

from symkern.nodes import Node, PlanGraph
from symkern.prompt_layer import ProgramSpec, PromptIntent


@dataclass(slots=True)
class OperatorGap:
    operator_id: str
    transformation_index: int


@dataclass(slots=True)
class PlanAssemblyResult:
    plan: PlanGraph | None
    gaps: list[OperatorGap]


@dataclass(slots=True)
class OperationSchema:
    op_id: str
    op_code: int
    signature: dict[str, object]
    machine_metadata: dict[str, object]
    handler: Callable[[Node, dict[str, object]], dict[str, object]]
    description: str = ""

    def to_descriptor(self) -> dict[str, object]:
        return {
            "op_code": self.op_code,
            "signature": dict(self.signature),
            "machine_metadata": dict(self.machine_metadata),
            "description": self.description,
        }


@dataclass(slots=True)
class RewriteRule:
    rule_id: str
    description: str


class MachineLanguage:
    SCHEMA_VERSION = "symkern.machine-language/v1alpha1"
    BUILTIN_OPCODES = {
        "core.stream_window": 101,
        "core.moving_baseline": 102,
        "core.score_delta": 103,
        "core.compare_threshold": 104,
        "core.emit_sink": 105,
        "core.generate_random_array": 201,
        "core.random_math_map": 202,
        "core.generate_gaussian_array": 203,
        "core.compute_array_statistics": 204,
        "core.generate_historical_dates": 205,
        "core.lookup_wikipedia_deaths": 206,
        "core.elect_illustrious_death": 207,
        "core.normalize_text_words": 301,
        "core.render_camel_case": 302,
        "core.render_snake_case": 303,
    }
    INVENTED_OPCODE_START = 1000
    SYNTHESIZED_OPERATOR_REGISTRY = ".symkern/operators/registry.json"

    def __init__(self, deployment_root: str | Path | None = None) -> None:
        self.op_registry_by_code: dict[int, OperationSchema] = {}
        self.rewrite_rules: list[RewriteRule] = []
        self._deployment_root: Path | None = Path(deployment_root) if deployment_root else None
        self._register_builtins()

    def _register_builtins(self) -> None:
        self._register_hardcoded_builtins()
        self._load_synthesized_operator_registry()

    def _register_hardcoded_builtins(self) -> None:
        self.register(
            OperationSchema(
                op_id="core.stream_window",
                op_code=self.BUILTIN_OPCODES["core.stream_window"],
                signature={"inputs": ["events"], "outputs": ["windowed_events"]},
                machine_metadata={"category": "stream"},
                handler=self._op_stream_window,
                description="Partition a stream into rolling windows.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.moving_baseline",
                op_code=self.BUILTIN_OPCODES["core.moving_baseline"],
                signature={"inputs": ["windowed_events"], "outputs": ["baseline"]},
                machine_metadata={"category": "analytics"},
                handler=self._op_moving_baseline,
                description="Compute rolling baselines.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.score_delta",
                op_code=self.BUILTIN_OPCODES["core.score_delta"],
                signature={"inputs": ["windowed_events", "baseline"], "outputs": ["scores"]},
                machine_metadata={"category": "analytics"},
                handler=self._op_score_delta,
                description="Score deviations from baseline.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.compare_threshold",
                op_code=self.BUILTIN_OPCODES["core.compare_threshold"],
                signature={"inputs": ["scores"], "outputs": ["detections"]},
                machine_metadata={"category": "decision"},
                handler=self._op_compare_threshold,
                description="Compare scores to an anomaly threshold.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.emit_sink",
                op_code=self.BUILTIN_OPCODES["core.emit_sink"],
                signature={"inputs": ["detections"], "outputs": ["emitted"]},
                machine_metadata={"category": "sink"},
                handler=self._op_emit_sink,
                description="Emit final detections to the configured sink.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.generate_random_array",
                op_code=self.BUILTIN_OPCODES["core.generate_random_array"],
                signature={"inputs": [], "outputs": ["source_array"]},
                machine_metadata={"category": "array"},
                handler=self._op_generate_random_array,
                description="Generate a bounded random integer array.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.random_math_map",
                op_code=self.BUILTIN_OPCODES["core.random_math_map"],
                signature={"inputs": ["source_array"], "outputs": ["mapped_array", "operations"]},
                machine_metadata={"category": "array"},
                handler=self._op_random_math_map,
                description="Apply randomized math operations to each array element.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.generate_gaussian_array",
                op_code=self.BUILTIN_OPCODES["core.generate_gaussian_array"],
                signature={"inputs": [], "outputs": ["source_array"]},
                machine_metadata={"category": "array"},
                handler=self._op_generate_gaussian_array,
                description="Generate a bounded gaussian-distributed numeric array.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.compute_array_statistics",
                op_code=self.BUILTIN_OPCODES["core.compute_array_statistics"],
                signature={"inputs": ["source_array"], "outputs": ["statistics"]},
                machine_metadata={"category": "analytics"},
                handler=self._op_compute_array_statistics,
                description="Compute summary statistics for a numeric array.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.generate_historical_dates",
                op_code=self.BUILTIN_OPCODES["core.generate_historical_dates"],
                signature={"inputs": [], "outputs": ["historical_dates"]},
                machine_metadata={"category": "planning"},
                handler=self._op_generate_historical_dates,
                description="Generate candidate historical dates for downstream lookup.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.lookup_wikipedia_deaths",
                op_code=self.BUILTIN_OPCODES["core.lookup_wikipedia_deaths"],
                signature={"inputs": ["historical_dates"], "outputs": ["death_candidates", "death_candidate_features"]},
                machine_metadata={"category": "lookup"},
                handler=self._op_lookup_wikipedia_deaths,
                description="Lookup Wikipedia death entries for each historical date and derive candidate features.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.elect_illustrious_death",
                op_code=self.BUILTIN_OPCODES["core.elect_illustrious_death"],
                signature={"inputs": ["death_candidate_features"], "outputs": ["selected_death"]},
                machine_metadata={"category": "decision"},
                handler=self._op_elect_illustrious_death,
                description="Select the most illustrious death candidate using derived feature scores.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.normalize_text_words",
                op_code=self.BUILTIN_OPCODES["core.normalize_text_words"],
                signature={"inputs": ["text"], "outputs": ["word_tokens"]},
                machine_metadata={"category": "text"},
                handler=self._op_normalize_text_words,
                description="Normalize input text into reusable word tokens.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.render_camel_case",
                op_code=self.BUILTIN_OPCODES["core.render_camel_case"],
                signature={"inputs": ["word_tokens"], "outputs": ["camel_case"]},
                machine_metadata={"category": "text"},
                handler=self._op_render_camel_case,
                description="Render normalized word tokens as camelCase.",
            )
        )
        self.register(
            OperationSchema(
                op_id="core.render_snake_case",
                op_code=self.BUILTIN_OPCODES["core.render_snake_case"],
                signature={"inputs": ["word_tokens"], "outputs": ["snake_case"]},
                machine_metadata={"category": "text"},
                handler=self._op_render_snake_case,
                description="Render normalized word tokens as snake_case.",
            )
        )

    def _load_synthesized_operator_registry(self) -> None:
        """Load dynamically synthesized operators from the durable operator registry."""
        if self._deployment_root:
            registry_path = self._deployment_root / ".symkern" / "operators" / "registry.json"
        else:
            registry_path = Path(self.SYNTHESIZED_OPERATOR_REGISTRY)
        if not registry_path.exists():
            return
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
            for entry in list(data.get("operators", [])):
                self._register_synthesized_entry(dict(entry))
        except Exception:
            pass  # corrupt registry does not crash startup

    def _register_synthesized_entry(self, entry: dict[str, object]) -> None:
        """Register one persisted synthesized operator entry."""
        from symkern.operator_compiler import compile_handler  # late import, avoids circular
        from symkern.operator_synthesis_contract import OperatorHandlerSpec

        op_id = str(entry.get("operator_id", ""))
        op_code = int(entry.get("op_code", 0))
        if not op_id or not op_code:
            return
        if op_code in self.op_registry_by_code:
            return

        kind = str(entry.get("implementation_kind", ""))
        if kind == "handler_spec":
            # Merge signature.inputs/outputs into top-level so from_dict picks them up
            sig = dict(entry.get("signature", {}))
            hydrated = {
                **entry,
                "inputs": entry.get("inputs") or sig.get("inputs", []),
                "outputs": entry.get("outputs") or sig.get("outputs", []),
            }
            spec = OperatorHandlerSpec.from_dict(hydrated)
            handler = compile_handler(spec)
        elif kind == "composition":
            invented_from = [int(c) for c in list(entry.get("invented_from_opcodes", []))]
            if not all(c in self.op_registry_by_code for c in invented_from):
                return  # dependency not yet loaded
            handler = self._build_invented_handler(invented_from)
        else:
            return

        self.register(
            OperationSchema(
                op_id=op_id,
                op_code=op_code,
                signature=dict(entry.get("signature", {})),
                machine_metadata=dict(entry.get("machine_metadata", {})),
                handler=handler,
                description=str(entry.get("description", "")),
            )
        )

    def persist_synthesized_operator(
        self,
        op_id: str,
        op_code: int,
        signature: dict[str, object],
        machine_metadata: dict[str, object],
        description: str,
        implementation_kind: str,
        implementation_payload: dict[str, object],
    ) -> None:
        """Persist a newly synthesized operator to the durable registry."""
        if self._deployment_root:
            registry_path = self._deployment_root / ".symkern" / "operators" / "registry.json"
        else:
            registry_path = Path(self.SYNTHESIZED_OPERATOR_REGISTRY)
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {}
        except Exception:
            data = {}
        operators = list(data.get("operators", []))
        # Avoid duplicates
        operators = [o for o in operators if str(o.get("operator_id", "")) != op_id]
        operators.append({
            "operator_id": op_id,
            "op_code": op_code,
            "signature": signature,
            "machine_metadata": machine_metadata,
            "description": description,
            "implementation_kind": implementation_kind,
            **implementation_payload,
        })
        registry_path.write_text(json.dumps({"operators": operators}, indent=2), encoding="utf-8")

    def register(self, schema: OperationSchema) -> None:
        self.op_registry_by_code[schema.op_code] = schema

    def allocate_invented_opcode(self) -> int:
        next_opcode = max(self.op_registry_by_code.keys(), default=self.INVENTED_OPCODE_START - 1) + 1
        return max(next_opcode, self.INVENTED_OPCODE_START)

    def register_descriptor(self, descriptor: dict[str, object]) -> None:
        op_code = int(descriptor.get("op_code", 0))
        if op_code in self.op_registry_by_code:
            return

        machine_metadata = dict(descriptor.get("machine_metadata", {}))
        invented_from_opcodes = [int(item) for item in list(machine_metadata.get("invented_from_opcodes", []))]
        metadata_projection_codes = {
            int(component_op_code): list(keys)
            for component_op_code, keys in dict(machine_metadata.get("metadata_projection_codes", {})).items()
        }
        if invented_from_opcodes:
            self.register(
                OperationSchema(
                    op_id="",
                    op_code=op_code,
                    signature=dict(descriptor.get("signature", {})),
                    machine_metadata=machine_metadata,
                    handler=self._build_invented_handler(invented_from_opcodes, metadata_projection_codes),
                    description=str(descriptor.get("description", "")),
                )
            )
            return
        raise ValueError(f"Cannot reconstruct unknown operation descriptor for opcode: {op_code}")

    def snapshot_for_plan(self, plan: PlanGraph, inventions: list[dict[str, object]]) -> dict[str, object]:
        used_op_codes = {node.op_code for node in plan.nodes if node.op_code is not None}
        operation_schemas = {
            str(op_code): self.op_registry_by_code[op_code].to_descriptor()
            for op_code in sorted(used_op_codes)
        }
        plan_snapshot = plan.to_dict()
        for node in list(plan_snapshot.get("nodes", [])):
            node.pop("op_id", None)
        invention_snapshot = []
        for invention in inventions:
            persisted_invention = dict(invention)
            persisted_invention.pop("op_id", None)
            persisted_invention.pop("source_ops", None)
            invention_snapshot.append(persisted_invention)
        return {
            "kind": "symkern.machine_language",
            "schema_version": self.SCHEMA_VERSION,
            "plan": plan_snapshot,
            "operation_schemas": operation_schemas,
            "inventions": invention_snapshot,
            "plan_metadata": dict(plan.metadata),
        }

    def capability_catalog(self) -> dict[str, object]:
        capabilities = []
        for op_code in sorted(self.op_registry_by_code):
            schema = self.op_registry_by_code[op_code]
            capabilities.append(
                {
                    "capability_id": schema.op_id or f"opcode.{op_code}",
                    "op_code": op_code,
                    "kind": "builtin_operator" if op_code < self.INVENTED_OPCODE_START else "invented_abstraction",
                    "signature": dict(schema.signature),
                    "metadata": dict(schema.machine_metadata),
                    "description": schema.description,
                }
            )
        return {
            "schema_version": "symkern.operator-capability-registry/v1alpha1",
            "capabilities": capabilities,
        }

    def assemble_plan_from_program_spec(self, spec: ProgramSpec, strategy: str = "spec") -> PlanAssemblyResult:
        """Generic registry-based assembler. Returns a PlanAssemblyResult with any missing-operator gaps."""    
        result = self._assemble_plan_internal(spec, strategy)
        return result

    def _assemble_plan_internal(self, spec: ProgramSpec, strategy: str = "spec") -> PlanAssemblyResult:
        """Core plan assembly: returns partial plan + list of OperatorGap for unknown operators."""
        op_by_id: dict[str, OperationSchema] = {
            schema.op_id: schema
            for schema in self.op_registry_by_code.values()
            if schema.op_id
        }

        plan = PlanGraph(
            plan_id=f"plan-{strategy}",
            state_bindings=dict(spec.state_bindings),
            metadata={
                "strategy": strategy,
                "program_id": spec.program_id,
                "requested_outputs": [dict(item) for item in spec.requested_outputs],
            },
        )
        plan.metadata["input_contract"] = [dict(item) for item in spec.requested_inputs]

        produced_by: dict[str, str] = {}
        gaps: list[OperatorGap] = []

        for idx, transformation in enumerate(spec.transformations):
            op_id = str(transformation.get("operator_id", "")).strip()
            if not op_id:
                gaps.append(OperatorGap(operator_id="", transformation_index=idx))
                continue
            schema = op_by_id.get(op_id)
            if schema is None:
                gaps.append(OperatorGap(operator_id=op_id, transformation_index=idx))
                continue

            node_id = f"n{idx + 1}"
            raw_inputs = list(transformation.get("inputs", []))
            raw_outputs = list(transformation.get("outputs", []))
            inp_names = [str(i.get("name", i) if isinstance(i, dict) else i) for i in raw_inputs]
            out_names = [str(o.get("name", o) if isinstance(o, dict) else o) for o in raw_outputs]
            if not inp_names:
                inp_names = list(schema.signature.get("inputs", []))
            if not out_names:
                out_names = list(schema.signature.get("outputs", []))

            extra_meta = {
                key: val for key, val in transformation.items()
                if key not in ("operator_id", "operator", "inputs", "outputs", "kind", "stage_id")
            }
            node = Node(node_id, op_code=schema.op_code, inputs=inp_names, outputs=out_names, metadata=extra_meta)
            plan.add_node(node)
            for out_name in out_names:
                produced_by[out_name] = node_id

        for node in plan.nodes:
            for inp in node.inputs:
                src = produced_by.get(inp)
                if src and src != node.node_id:
                    plan.add_edge(src, node.node_id)

        # Auto-append emit_sink if spec doesn't include one and there are no gaps
        if not gaps:
            transformation_op_ids = {str(t.get("operator_id", "")) for t in spec.transformations}
            if "core.emit_sink" not in transformation_op_ids:
                sink_inputs = [str(item.get("name", "")) for item in spec.requested_outputs]
                sink_node_id = f"n{len(spec.transformations) + 1}"
                sink_node = Node(
                    sink_node_id,
                    op_code=self.BUILTIN_OPCODES["core.emit_sink"],
                    inputs=sink_inputs,
                    outputs=["emitted"],
                    metadata={"sinks": list(spec.state_bindings.get("sinks", ["stdout"]))},
                )
                plan.add_node(sink_node)
                for inp in sink_inputs:
                    src = produced_by.get(inp)
                    if src:
                        plan.add_edge(src, sink_node_id)

        return PlanAssemblyResult(plan=plan if not gaps else None, gaps=gaps)

    def build_plan_from_program_spec(self, spec: ProgramSpec, strategy: str = "spec") -> PlanGraph:
        """Compile a ProgramSpec; raises ValueError if any operator_id is unknown."""
        result = self._assemble_plan_internal(spec, strategy)
        if result.gaps:
            unknown = [g.operator_id for g in result.gaps if g.operator_id]
            raise ValueError(f"Unknown operators: {unknown}")
        return result.plan  # type: ignore[return-value]

    def build_plan(self, intent: PromptIntent, strategy: str = "default") -> PlanGraph:
        plan = PlanGraph(
            plan_id=f"plan-{strategy}",
            state_bindings=dict(intent.state),
            metadata={"strategy": strategy, "goals": list(intent.goals)},
        )

        if any(goal == "detect_stream_anomalies" for goal in intent.goals):
            plan.metadata["input_contract"] = [
                {
                    "name": "events",
                    "kind": "event_stream",
                    "required": False,
                    "source": "invoke-time",
                    "description": "Optional external event stream. If omitted, synthetic events may be used by the caller.",
                }
            ]
            nodes = [
                Node("n1", op_code=self.BUILTIN_OPCODES["core.stream_window"], outputs=["windowed_events"], metadata={"window_size": intent.state.get("window_size", 5)}),
                Node("n2", op_code=self.BUILTIN_OPCODES["core.moving_baseline"], inputs=["windowed_events"], outputs=["baseline"]),
                Node("n3", op_code=self.BUILTIN_OPCODES["core.score_delta"], inputs=["windowed_events", "baseline"], outputs=["scores"]),
                Node("n4", op_code=self.BUILTIN_OPCODES["core.compare_threshold"], inputs=["scores"], outputs=["detections"], metadata={"threshold": 2.4 if strategy == "conservative" else 2.0}),
                Node("n5", op_code=self.BUILTIN_OPCODES["core.emit_sink"], inputs=["detections"], outputs=["emitted"], metadata={"sinks": intent.sinks}),
            ]
            for node in nodes:
                plan.add_node(node)
            for source, target in (("n1", "n2"), ("n1", "n3"), ("n2", "n3"), ("n3", "n4"), ("n4", "n5")):
                plan.add_edge(source, target)
            return plan

        if any(goal == "generate_random_mapped_array" for goal in intent.goals):
            plan.metadata["input_contract"] = [
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
                    "description": "Optional external source array. If omitted, the program synthesizes one internally.",
                }
            ]
            nodes = [
                Node(
                    "n1",
                    op_code=self.BUILTIN_OPCODES["core.generate_random_array"],
                    outputs=["source_array"],
                    metadata={
                        "length": intent.state.get("length", 5),
                        "min_value": intent.state.get("min_value", 1),
                        "max_value": intent.state.get("max_value", 10),
                        "accept_invoke_input": True,
                    },
                ),
                Node(
                    "n2",
                    op_code=self.BUILTIN_OPCODES["core.random_math_map"],
                    inputs=["source_array"],
                    outputs=["mapped_array", "operations"],
                    metadata={"operation_pool": intent.state.get("operation_pool", ["add", "subtract", "multiply"])},
                ),
                Node(
                    "n3",
                    op_code=self.BUILTIN_OPCODES["core.emit_sink"],
                    inputs=["mapped_array", "operations", "source_array"],
                    outputs=["emitted"],
                    metadata={"sinks": intent.sinks, "emission_kind": "array_map"},
                ),
            ]
            for node in nodes:
                plan.add_node(node)
            for source, target in (("n1", "n2"), ("n1", "n3"), ("n2", "n3")):
                plan.add_edge(source, target)
            return plan

        if any(goal == "generate_gaussian_array_statistics" for goal in intent.goals):
            plan.metadata["input_contract"] = [
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
                    "description": "Optional external numeric array. If omitted, the program synthesizes one internally.",
                }
            ]
            nodes = [
                Node(
                    "n1",
                    op_code=self.BUILTIN_OPCODES["core.generate_gaussian_array"],
                    outputs=["source_array"],
                    metadata={
                        "length": intent.state.get("length", 20),
                        "min_value": intent.state.get("min_value", 0),
                        "max_value": intent.state.get("max_value", 20),
                        "accept_invoke_input": True,
                    },
                ),
                Node(
                    "n2",
                    op_code=self.BUILTIN_OPCODES["core.compute_array_statistics"],
                    inputs=["source_array"],
                    outputs=["statistics"],
                    metadata={"requested_statistics": list(intent.state.get("requested_statistics", ["standard_deviation", "mean", "median"]))},
                ),
                Node(
                    "n3",
                    op_code=self.BUILTIN_OPCODES["core.emit_sink"],
                    inputs=["source_array", "statistics"],
                    outputs=["emitted"],
                    metadata={"sinks": intent.sinks, "emission_kind": "array_statistics"},
                ),
            ]
            for node in nodes:
                plan.add_node(node)
            for source, target in (("n1", "n2"), ("n1", "n3"), ("n2", "n3")):
                plan.add_edge(source, target)
            return plan

        if any(goal == "elect_illustrious_historical_death" for goal in intent.goals):
            plan.metadata["input_contract"] = [
                {
                    "name": "historical_dates",
                    "kind": "array[historical_date]",
                    "required": False,
                    "source": "invoke-time",
                    "constraints": {
                        "expected_length": int(intent.state.get("date_count", 3)),
                    },
                    "description": "Optional external list of historical dates. If omitted, the program synthesizes dates internally.",
                }
            ]
            nodes = [
                Node(
                    "n1",
                    op_code=self.BUILTIN_OPCODES["core.generate_historical_dates"],
                    outputs=["historical_dates"],
                    metadata={"date_count": intent.state.get("date_count", 3)},
                ),
                Node(
                    "n2",
                    op_code=self.BUILTIN_OPCODES["core.lookup_wikipedia_deaths"],
                    inputs=["historical_dates"],
                    outputs=["death_candidates", "death_candidate_features"],
                    metadata={"lookup_source": intent.state.get("lookup_source", "wikipedia.org")},
                ),
                Node(
                    "n3",
                    op_code=self.BUILTIN_OPCODES["core.elect_illustrious_death"],
                    inputs=["death_candidate_features"],
                    outputs=["selected_death"],
                    metadata={"selection_goal": intent.state.get("selection_goal", "most_illustrious_death")},
                ),
                Node(
                    "n4",
                    op_code=self.BUILTIN_OPCODES["core.emit_sink"],
                    inputs=["historical_dates", "death_candidates", "selected_death"],
                    outputs=["emitted"],
                    metadata={"sinks": intent.sinks, "emission_kind": "historical_death_election"},
                ),
            ]
            for node in nodes:
                plan.add_node(node)
            for source, target in (("n1", "n2"), ("n2", "n3"), ("n1", "n4"), ("n2", "n4"), ("n3", "n4")):
                plan.add_edge(source, target)
            return plan

        plan.add_node(Node("n1", op_code=self.BUILTIN_OPCODES["core.emit_sink"], outputs=["emitted"], metadata={"sinks": intent.sinks, "message": intent.goals[0]}))
        return plan

    def execute_node(self, node: Node, context: dict[str, object]) -> dict[str, object]:
        if node.op_code is not None:
            schema = self.op_registry_by_code[node.op_code]
        else:
            schema = self.op_registry_by_code[self._legacy_opcode_for_label(node.op_id)]
        return schema.handler(node, context)

    def _legacy_opcode_for_label(self, op_id: str) -> int:
        if op_id in self.BUILTIN_OPCODES:
            return self.BUILTIN_OPCODES[op_id]
        for op_code, schema in self.op_registry_by_code.items():
            if schema.op_id == op_id:
                return op_code
        raise KeyError(f"Unknown legacy operation label: {op_id}")

    def execute_plan(self, plan: PlanGraph, context: dict[str, object] | None = None) -> dict[str, object]:
        working_context = dict(context or {})
        outputs: dict[str, object] = {}
        for node in plan.ordered_nodes():
            result = self.execute_node(node, working_context)
            working_context.update(result)
            outputs.update(result)
        return outputs

    def _build_invented_handler(
        self,
        source_op_codes: list[int],
        metadata_projection: dict[int, list[str]] | None = None,
    ) -> Callable[[Node, dict[str, object]], dict[str, object]]:
        projected_metadata = metadata_projection or {}

        def invented_handler(node: Node, context: dict[str, object]) -> dict[str, object]:
            working_context = dict(context)
            outputs: dict[str, object] = {}
            for index, op_code in enumerate(source_op_codes, start=1):
                component_metadata = {
                    key: node.metadata[key]
                    for key in projected_metadata.get(op_code, [])
                    if key in node.metadata
                }
                component_node = Node(
                    node_id=f"{node.node_id}.component_{index}",
                    op_code=op_code,
                    metadata=component_metadata,
                )
                result = self.op_registry_by_code[op_code].handler(component_node, working_context)
                working_context.update(result)
                outputs.update(result)
            return outputs

        return invented_handler

    @staticmethod
    def _op_stream_window(node: Node, context: dict[str, object]) -> dict[str, object]:
        events = list(context.get("events", []))
        window_size = int(node.metadata.get("window_size", 5))
        windows = [events[index:index + window_size] for index in range(0, len(events), window_size) if events[index:index + window_size]]
        return {"windowed_events": windows}

    @staticmethod
    def _op_moving_baseline(node: Node, context: dict[str, object]) -> dict[str, object]:
        baselines: list[float] = []
        for window in context.get("windowed_events", []):
            values = [float(event["value"]) for event in window]
            baselines.append(mean(values) if values else 0.0)
        return {"baseline": baselines}

    @staticmethod
    def _op_score_delta(node: Node, context: dict[str, object]) -> dict[str, object]:
        scores: list[float] = []
        for window, baseline in zip(context.get("windowed_events", []), context.get("baseline", []), strict=False):
            values = [float(event["value"]) for event in window]
            window_peak = max(values) if values else 0.0
            scores.append(abs(window_peak - baseline))
        return {"scores": scores}

    @staticmethod
    def _op_compare_threshold(node: Node, context: dict[str, object]) -> dict[str, object]:
        threshold = float(node.metadata.get("threshold", 2.0))
        detections = [index for index, score in enumerate(context.get("scores", [])) if score >= threshold]
        return {"detections": detections}

    @staticmethod
    def _op_emit_sink(node: Node, context: dict[str, object]) -> dict[str, object]:
        if node.metadata.get("emission_kind") == "array_map":
            return {
                "emitted": {
                    "source_array": list(context.get("source_array", [])),
                    "mapped_array": list(context.get("mapped_array", [])),
                    "operations": list(context.get("operations", [])),
                    "sinks": node.metadata.get("sinks", []),
                }
            }
        if node.metadata.get("emission_kind") == "array_statistics":
            return {
                "emitted": {
                    "source_array": list(context.get("source_array", [])),
                    "statistics": dict(context.get("statistics", {})),
                    "sinks": node.metadata.get("sinks", []),
                }
            }
        if node.metadata.get("emission_kind") == "historical_death_election":
            return {
                "emitted": {
                    "historical_dates": list(context.get("historical_dates", [])),
                    "death_candidates": list(context.get("death_candidates", [])),
                    "selected_death": dict(context.get("selected_death", {})),
                    "sinks": node.metadata.get("sinks", []),
                }
            }
        if node.metadata.get("emission_kind") == "text_case_conversion":
            return {
                "emitted": {
                    "text": str(context.get("text", "")),
                    "camel_case": str(context.get("camel_case", "")),
                    "snake_case": str(context.get("snake_case", "")),
                    "sinks": node.metadata.get("sinks", []),
                }
            }
        if "message" in node.metadata:
            return {"emitted": {"message": node.metadata["message"], "sinks": node.metadata.get("sinks", [])}}
        # Generic fallback: collect all declared inputs from context
        collected: dict[str, object] = {}
        for inp_name in node.inputs:
            if inp_name in context:
                val = context[inp_name]
                collected[inp_name] = list(val) if isinstance(val, list) else val
        collected["sinks"] = node.metadata.get("sinks", [])
        return {"emitted": collected}

    @staticmethod
    def _op_normalize_text_words(node: Node, context: dict[str, object]) -> dict[str, object]:
        text = str(context.get("text", ""))
        words = [token.lower() for token in re.findall(r"[A-Za-z0-9]+", text)]
        return {"word_tokens": words}

    @staticmethod
    def _op_render_camel_case(node: Node, context: dict[str, object]) -> dict[str, object]:
        words = [str(item) for item in context.get("word_tokens", [])]
        if not words:
            return {"camel_case": ""}
        head, *tail = words
        return {"camel_case": head + "".join(word[:1].upper() + word[1:] for word in tail)}

    @staticmethod
    def _op_render_snake_case(node: Node, context: dict[str, object]) -> dict[str, object]:
        words = [str(item) for item in context.get("word_tokens", [])]
        return {"snake_case": "_".join(words)}

    @staticmethod
    def _op_generate_matrix(node: Node, context: dict[str, object]) -> dict[str, object]:
        if "matrix" in context:
            return {"matrix": list(context["matrix"])}
        seed = int(context.get("seed", 17))
        generator = random.Random(seed)
        rows = int(node.metadata.get("rows", 5))
        cols = int(node.metadata.get("cols", rows))
        min_value = int(node.metadata.get("min_value", 1))
        max_value = int(node.metadata.get("max_value", 10))
        matrix = [[generator.randint(min_value, max_value) for _ in range(cols)] for _ in range(rows)]
        return {"matrix": matrix}

    @staticmethod
    def _op_extract_diagonal(node: Node, context: dict[str, object]) -> dict[str, object]:
        matrix = list(context.get("matrix", []))
        diagonal = []
        for i, row in enumerate(matrix):
            row_list = list(row)
            if i < len(row_list):
                diagonal.append(row_list[i])
        return {"diagonal": diagonal}

    @staticmethod
    def _op_sum_integers(node: Node, context: dict[str, object]) -> dict[str, object]:
        input_name = node.inputs[0] if node.inputs else "diagonal"
        output_name = node.outputs[0] if node.outputs else "sum"
        values = list(context.get(input_name, []))
        return {output_name: sum(int(v) for v in values)}

    @staticmethod
    def _op_generate_random_array(node: Node, context: dict[str, object]) -> dict[str, object]:
        if "source_array" in context:
            return {"source_array": list(context.get("source_array", []))}
        seed = context.get("seed", 17)
        generator = random.Random(seed)
        length = int(node.metadata.get("length", 5))
        min_value = int(node.metadata.get("min_value", 1))
        max_value = int(node.metadata.get("max_value", 10))
        values = [generator.randint(min_value, max_value) for _ in range(length)]
        return {"source_array": values}

    @staticmethod
    def _op_random_math_map(node: Node, context: dict[str, object]) -> dict[str, object]:
        source_array = [int(value) for value in context.get("source_array", [])]
        seed = context.get("seed", 17) + 1
        generator = random.Random(seed)
        operation_pool = list(node.metadata.get("operation_pool", ["add", "subtract", "multiply"]))

        mapped: list[int] = []
        operations: list[str] = []
        for value in source_array:
            operation = generator.choice(operation_pool)
            operand = generator.randint(1, 3)
            if operation == "add":
                result = value + operand
            elif operation == "subtract":
                result = value - operand
            else:
                result = value * operand
            mapped.append(result)
            operations.append(f"{operation}:{operand}")

        return {"mapped_array": mapped, "operations": operations}

    @staticmethod
    def _op_generate_gaussian_array(node: Node, context: dict[str, object]) -> dict[str, object]:
        if "source_array" in context:
            return {"source_array": list(context.get("source_array", []))}
        seed = context.get("seed", 17)
        generator = random.Random(seed)
        length = int(node.metadata.get("length", 20))
        min_value = float(node.metadata.get("min_value", 0))
        max_value = float(node.metadata.get("max_value", 20))
        midpoint = (min_value + max_value) / 2.0
        sigma = max((max_value - min_value) / 6.0, 0.0001)
        values = [
            round(min(max(generator.gauss(midpoint, sigma), min_value), max_value), 4)
            for _ in range(length)
        ]
        return {"source_array": values}

    @staticmethod
    def _op_compute_array_statistics(node: Node, context: dict[str, object]) -> dict[str, object]:
        values = [float(value) for value in context.get("source_array", [])]
        requested = list(node.metadata.get("requested_statistics", ["standard_deviation", "mean", "median"]))
        statistics: dict[str, float] = {}
        if not values:
            return {"statistics": statistics}
        if "standard_deviation" in requested:
            statistics["standard_deviation"] = round(pstdev(values), 4)
        if "mean" in requested:
            statistics["mean"] = round(mean(values), 4)
        if "median" in requested:
            statistics["median"] = round(median(values), 4)
        return {"statistics": statistics}

    @staticmethod
    def _op_generate_historical_dates(node: Node, context: dict[str, object]) -> dict[str, object]:
        if "historical_dates" in context:
            return {"historical_dates": list(context.get("historical_dates", []))}

        seed = int(context.get("seed", 17))
        generator = random.Random(seed)
        date_count = int(node.metadata.get("date_count", 3))
        month_lengths = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
        historical_dates: list[dict[str, object]] = []
        seen: set[str] = set()
        while len(historical_dates) < date_count:
            year = generator.randint(1600, 2015)
            month = generator.randint(1, 12)
            day = generator.randint(1, month_lengths[month])
            label = f"{year:04d}-{month:02d}-{day:02d}"
            if label in seen:
                continue
            seen.add(label)
            historical_dates.append({"year": year, "month": month, "day": day, "label": label})
        return {"historical_dates": historical_dates}

    @staticmethod
    def _op_lookup_wikipedia_deaths(node: Node, context: dict[str, object]) -> dict[str, object]:
        historical_dates = list(context.get("historical_dates", []))
        lookup_override = dict(context.get("historical_death_lookup", {}))
        candidates: list[dict[str, object]] = []
        candidate_features: list[dict[str, object]] = []
        keyword_weights = [
            "president", "prime minister", "king", "queen", "emperor", "pope", "saint", "scientist",
            "mathematician", "physicist", "writer", "poet", "composer", "artist", "philosopher", "general",
            "explorer", "inventor", "nobel", "actor",
        ]

        for item in historical_dates:
            label = str(item.get("label", ""))
            if label in lookup_override:
                date_candidates = list(lookup_override[label])
            else:
                date_candidates = MachineLanguage._fetch_wikipedia_deaths_for_date(int(item.get("month", 1)), int(item.get("day", 1)), label)
            for candidate in date_candidates:
                person = str(candidate.get("person", ""))
                description = str(candidate.get("description", ""))
                combined = f"{person} {description}".lower()
                keyword_hits = sum(1 for keyword in keyword_weights if keyword in combined)
                feature = {
                    "candidate_id": f"{label}:{person}",
                    "person": person,
                    "date": label,
                    "year": int(candidate.get("year", 0)),
                    "description": description,
                    "wikipedia_url": str(candidate.get("wikipedia_url", "")),
                    "page_count": int(candidate.get("page_count", 1)),
                    "description_length": len(description),
                    "keyword_hits": keyword_hits,
                    "era_bonus": max(0, min(10, (1950 - int(candidate.get("year", 0))) // 50 + 2)),
                }
                candidates.append(
                    {
                        "candidate_id": feature["candidate_id"],
                        "person": person,
                        "date": label,
                        "year": feature["year"],
                        "description": description,
                        "wikipedia_url": feature["wikipedia_url"],
                    }
                )
                candidate_features.append(feature)

        return {"death_candidates": candidates, "death_candidate_features": candidate_features}

    @staticmethod
    def _fetch_wikipedia_deaths_for_date(month: int, day: int, label: str) -> list[dict[str, object]]:
        request = urllib.request.Request(
            url=f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/deaths/{month}/{day}",
            headers={"User-Agent": "symkern/0.1 (prototype)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return []

        results: list[dict[str, object]] = []
        for raw_entry in list(payload.get("deaths", []))[:12]:
            pages = list(raw_entry.get("pages", []))
            if not pages:
                continue
            page = pages[0]
            person = str(page.get("titles", {}).get("normalized") or page.get("title") or raw_entry.get("text", ""))
            description = str(page.get("description") or raw_entry.get("text") or "")
            results.append(
                {
                    "person": person,
                    "year": int(raw_entry.get("year", 0)),
                    "description": description,
                    "wikipedia_url": str(page.get("content_urls", {}).get("desktop", {}).get("page", "")),
                    "page_count": len(pages),
                    "date": label,
                }
            )
        return results

    @staticmethod
    def _op_elect_illustrious_death(node: Node, context: dict[str, object]) -> dict[str, object]:
        features = list(context.get("death_candidate_features", []))
        if not features:
            return {"selected_death": {}}
        ranked = max(features, key=MachineLanguage._illustrious_score)
        return {
            "selected_death": {
                "candidate_id": ranked.get("candidate_id", ""),
                "person": ranked.get("person", ""),
                "date": ranked.get("date", ""),
                "year": ranked.get("year", 0),
                "description": ranked.get("description", ""),
                "wikipedia_url": ranked.get("wikipedia_url", ""),
                "illustrious_score": MachineLanguage._illustrious_score(ranked),
            }
        }

    @staticmethod
    def _illustrious_score(feature: dict[str, object]) -> int:
        keyword_hits = int(feature.get("keyword_hits", 0))
        description_length = int(feature.get("description_length", 0))
        page_count = int(feature.get("page_count", 1))
        era_bonus = int(feature.get("era_bonus", 0))
        return (keyword_hits * 1000) + (page_count * 125) + description_length + (era_bonus * 40)
