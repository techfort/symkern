from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import mean

from symkern.nodes import Node, PlanGraph
from symkern.prompt_layer import PromptIntent


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
    }
    INVENTED_OPCODE_START = 1000

    def __init__(self) -> None:
        self.op_registry_by_code: dict[int, OperationSchema] = {}
        self.rewrite_rules: list[RewriteRule] = []
        self._register_builtins()

    def _register_builtins(self) -> None:
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

    def build_plan(self, intent: PromptIntent, strategy: str = "default") -> PlanGraph:
        plan = PlanGraph(
            plan_id=f"plan-{strategy}",
            state_bindings=dict(intent.state),
            metadata={"strategy": strategy, "goals": list(intent.goals)},
        )

        if any(goal == "detect_stream_anomalies" for goal in intent.goals):
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
            nodes = [
                Node(
                    "n1",
                    op_code=self.BUILTIN_OPCODES["core.generate_random_array"],
                    outputs=["source_array"],
                    metadata={
                        "length": intent.state.get("length", 5),
                        "min_value": intent.state.get("min_value", 1),
                        "max_value": intent.state.get("max_value", 10),
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
        if "message" in node.metadata:
            return {"emitted": {"message": node.metadata["message"], "sinks": node.metadata.get("sinks", [])}}
        return {"emitted": {"detections": list(context.get("detections", [])), "sinks": node.metadata.get("sinks", [])}}

    @staticmethod
    def _op_generate_random_array(node: Node, context: dict[str, object]) -> dict[str, object]:
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
