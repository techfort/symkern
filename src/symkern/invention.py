from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from symkern.machine_language import MachineLanguage, OperationSchema
from symkern.nodes import Node, PlanGraph


@dataclass(slots=True)
class InventionCandidate:
    op_id: str
    source_ops: list[str]
    score: float
    rationale: str
    op_code: int | None = None
    source_op_codes: list[int] = field(default_factory=list)
    accepted: bool = False
    metadata: dict[str, object] = field(default_factory=dict)
    signature: dict[str, list[str]] = field(default_factory=dict)
    replacement_metadata: dict[str, object] = field(default_factory=dict)
    metadata_projection: dict[str, list[str]] = field(default_factory=dict)
    metadata_projection_codes: dict[int, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class InventionPattern:
    op_id: str
    source_op_codes: list[int]
    source_ops: list[str]
    score: float
    rationale: str
    signature: dict[str, list[str]]
    metadata: dict[str, object] = field(default_factory=dict)
    metadata_projection: dict[str, list[str]] = field(default_factory=dict)
    metadata_projection_codes: dict[int, list[str]] = field(default_factory=dict)
    replacement_metadata_builder: Callable[[list[Node]], dict[str, object]] = lambda _nodes: {}


class InventionEngine:
    def __init__(self) -> None:
        self.patterns = [
            InventionPattern(
                op_id="invented.detect_stream_anomaly",
                source_op_codes=[
                    MachineLanguage.BUILTIN_OPCODES["core.score_delta"],
                    MachineLanguage.BUILTIN_OPCODES["core.compare_threshold"],
                ],
                source_ops=["core.score_delta", "core.compare_threshold"],
                score=0.86,
                rationale="Repeated anomaly scoring and thresholding can be compressed into a reusable schema.",
                signature={"inputs": ["windowed_events", "baseline"], "outputs": ["scores", "detections"]},
                metadata={"compression_gain": 2, "kind": "sequence_specialization"},
                metadata_projection={"core.compare_threshold": ["threshold"]},
                metadata_projection_codes={MachineLanguage.BUILTIN_OPCODES["core.compare_threshold"]: ["threshold"]},
                replacement_metadata_builder=lambda nodes: {"threshold": nodes[1].metadata.get("threshold", 2.0)},
            ),
            InventionPattern(
                op_id="invented.generate_random_mapped_array",
                source_op_codes=[
                    MachineLanguage.BUILTIN_OPCODES["core.generate_random_array"],
                    MachineLanguage.BUILTIN_OPCODES["core.random_math_map"],
                ],
                source_ops=["core.generate_random_array", "core.random_math_map"],
                score=0.79,
                rationale="Random array generation and randomized element mapping can be fused into a reusable array transformation schema.",
                signature={"inputs": [], "outputs": ["source_array", "mapped_array", "operations"]},
                metadata={"compression_gain": 2, "kind": "pipeline_specialization"},
                metadata_projection={
                    "core.generate_random_array": ["length", "min_value", "max_value"],
                    "core.random_math_map": ["operation_pool"],
                },
                metadata_projection_codes={
                    MachineLanguage.BUILTIN_OPCODES["core.generate_random_array"]: ["length", "min_value", "max_value"],
                    MachineLanguage.BUILTIN_OPCODES["core.random_math_map"]: ["operation_pool"],
                },
                replacement_metadata_builder=lambda nodes: {
                    "length": nodes[0].metadata.get("length", 5),
                    "min_value": nodes[0].metadata.get("min_value", 1),
                    "max_value": nodes[0].metadata.get("max_value", 10),
                    "operation_pool": list(nodes[1].metadata.get("operation_pool", ["add", "subtract", "multiply"])),
                },
            ),
        ]

    def propose(self, plan: PlanGraph) -> list[InventionCandidate]:
        candidates: list[InventionCandidate] = []
        for pattern in self.patterns:
            matched_nodes = self._match_pattern_nodes(plan, pattern.source_op_codes)
            if matched_nodes is None:
                continue
            candidates.append(
                InventionCandidate(
                    op_id=pattern.op_id,
                    source_ops=list(pattern.source_ops),
                    source_op_codes=list(pattern.source_op_codes),
                    score=pattern.score,
                    rationale=pattern.rationale,
                    metadata=dict(pattern.metadata),
                    signature={
                        "inputs": list(pattern.signature.get("inputs", [])),
                        "outputs": list(pattern.signature.get("outputs", [])),
                    },
                    replacement_metadata=pattern.replacement_metadata_builder(matched_nodes),
                    metadata_projection={op_id: list(keys) for op_id, keys in pattern.metadata_projection.items()},
                    metadata_projection_codes={op_code: list(keys) for op_code, keys in pattern.metadata_projection_codes.items()},
                )
            )
        return candidates

    def accept(self, candidate: InventionCandidate, language: MachineLanguage) -> InventionCandidate:
        for op_code, schema in language.op_registry_by_code.items():
            if schema.op_id == candidate.op_id:
                candidate.accepted = True
                candidate.op_code = op_code
                return candidate

        candidate.op_code = language.allocate_invented_opcode()

        language.register(
            OperationSchema(
                op_id=candidate.op_id,
                op_code=int(candidate.op_code),
                signature={
                    "inputs": list(candidate.signature.get("inputs", [])),
                    "outputs": list(candidate.signature.get("outputs", [])),
                },
                machine_metadata={
                    "invented_from": list(candidate.source_ops),
                    "invented_from_opcodes": list(candidate.source_op_codes),
                    "metadata_projection": {op_id: list(keys) for op_id, keys in candidate.metadata_projection.items()},
                    "metadata_projection_codes": {str(op_code): list(keys) for op_code, keys in candidate.metadata_projection_codes.items()},
                    **candidate.metadata,
                },
                handler=language._build_invented_handler(candidate.source_op_codes, candidate.metadata_projection_codes),
                description=candidate.rationale,
            )
        )
        candidate.accepted = True
        return candidate

    def rewrite_plan(self, plan: PlanGraph, candidate: InventionCandidate) -> PlanGraph:
        matched_nodes = self._match_pattern_nodes(plan, candidate.source_op_codes)
        if matched_nodes is None:
            return plan

        rewritten = PlanGraph(
            plan_id=plan.plan_id,
            state_bindings=dict(plan.state_bindings),
            metadata={
                **plan.metadata,
                "rewrites_applied": [*list(plan.metadata.get("rewrites_applied", [])), candidate.op_code],
            },
        )

        first_node = matched_nodes[0]
        replacement_node = Node(
            node_id=f"{first_node.node_id}_invented",
            op_code=candidate.op_code,
            inputs=list(first_node.inputs),
            outputs=list(candidate.signature.get("outputs", [])),
            execution_mode=first_node.execution_mode,
            metadata=dict(candidate.replacement_metadata),
            provenance={"rewritten_from": [node.node_id for node in matched_nodes]},
        )

        removed_ids = {node.node_id for node in matched_nodes}
        for node in plan.nodes:
            if node.node_id in removed_ids:
                continue
            rewritten.add_node(node)
        rewritten.add_node(replacement_node)

        edge_set: set[tuple[str, str]] = set()
        for source, target in plan.edges:
            if source in removed_ids and target in removed_ids:
                continue
            if target in removed_ids and source not in removed_ids:
                edge_set.add((source, replacement_node.node_id))
                continue
            if source in removed_ids and target not in removed_ids:
                edge_set.add((replacement_node.node_id, target))
                continue
            if source not in removed_ids and target not in removed_ids:
                edge_set.add((source, target))

        for source, target in sorted(edge_set):
            rewritten.add_edge(source, target)
        return rewritten

    @staticmethod
    def _match_pattern_nodes(plan: PlanGraph, source_op_codes: list[int]) -> list[Node] | None:
        ordered_nodes = plan.ordered_nodes()
        window = len(source_op_codes)
        if window == 0:
            return None
        for index in range(len(ordered_nodes) - window + 1):
            candidate_nodes = ordered_nodes[index:index + window]
            if [node.op_code for node in candidate_nodes] == source_op_codes:
                return candidate_nodes
        return None
