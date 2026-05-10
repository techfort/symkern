from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from symkern.artifacts import ArtifactBundle, ArtifactStore
from symkern.invention import InventionEngine
from symkern.logging import ExecutionTrace
from symkern.machine_language import MachineLanguage
from symkern.nodes import PlanGraph
from symkern.prompt_layer import PromptIntent


@dataclass(slots=True)
class ConvergenceResult:
    status: str
    plan: PlanGraph
    outputs: dict[str, object]
    reason_codes: list[str] = field(default_factory=list)
    inventions: list[dict[str, object]] = field(default_factory=list)
    trace: ExecutionTrace = field(default_factory=ExecutionTrace)
    score: float = 0.0
    language_snapshot: dict[str, object] = field(default_factory=dict)


class SymKernel:
    def __init__(self, language: MachineLanguage | None = None, invention_engine: InventionEngine | None = None) -> None:
        self.language = language or MachineLanguage()
        self.invention_engine = invention_engine or InventionEngine()

    def run(self, intent: PromptIntent, context: dict[str, object] | None = None, strategy: str = "default") -> ConvergenceResult:
        working_context = dict(context or {})
        trace = ExecutionTrace()
        trace.record("compile", "Intent compiled into a machine plan request.", goals=intent.goals)
        plan = self.language.build_plan(intent, strategy=strategy)
        trace.record("synthesize", "Plan graph synthesized.", plan_id=plan.plan_id, nodes=len(plan.nodes))

        inventions = []
        for candidate in self.invention_engine.propose(plan):
            accepted = self.invention_engine.accept(candidate, self.language)
            plan = self.invention_engine.rewrite_plan(plan, accepted)
            inventions.append(
                {
                    "op_code": accepted.op_code,
                    "source_op_codes": list(accepted.source_op_codes),
                    "score": accepted.score,
                    "accepted": accepted.accepted,
                    "rationale": accepted.rationale,
                    "metadata": dict(accepted.metadata),
                }
            )
            trace.record("invent", f"Accepted new abstraction opcode {accepted.op_code}.", op_code=accepted.op_code, score=accepted.score)
            trace.record("rewrite", f"Plan rewritten to use opcode {accepted.op_code}.", op_code=accepted.op_code, plan_id=plan.plan_id)

        outputs = self._execute_plan(plan, working_context, trace)

        reason_codes = ["goal_satisfied"] if outputs else ["no_outputs"]
        score = self._score(outputs, intent, strategy)
        status = "success" if outputs else "impossible"
        trace.record("converge", "Kernel finished execution.", status=status, score=score)
        return ConvergenceResult(
            status=status,
            plan=plan,
            outputs=outputs,
            reason_codes=reason_codes,
            inventions=inventions,
            trace=trace,
            score=score,
            language_snapshot=self.language.snapshot_for_plan(plan, inventions),
        )

    def replay_language(self, language_document: dict[str, object], context: dict[str, object] | None = None) -> ConvergenceResult:
        schema_version = str(language_document.get("schema_version", ""))
        if schema_version != MachineLanguage.SCHEMA_VERSION:
            raise ValueError(f"Unsupported machine language schema version: {schema_version}")

        language = MachineLanguage()
        for descriptor in dict(language_document.get("operation_schemas", {})).values():
            language.register_descriptor(dict(descriptor))

        plan = PlanGraph.from_dict(dict(language_document["plan"]))
        trace = ExecutionTrace()
        trace.record("replay", "Loaded persisted machine language.", plan_id=plan.plan_id)
        outputs = self._execute_plan(plan, dict(context or {}), trace, language=language)
        status = "success" if outputs else "impossible"
        reason_codes = ["goal_satisfied"] if outputs else ["no_outputs"]
        trace.record("converge", "Replay finished execution.", status=status, score=0.7 if outputs else 0.0)
        return ConvergenceResult(
            status=status,
            plan=plan,
            outputs=outputs,
            reason_codes=reason_codes,
            inventions=list(language_document.get("inventions", [])),
            trace=trace,
            score=0.7 if outputs else 0.0,
            language_snapshot=dict(language_document),
        )

    def _execute_plan(
        self,
        plan: PlanGraph,
        context: dict[str, object],
        trace: ExecutionTrace,
        language: MachineLanguage | None = None,
    ) -> dict[str, object]:
        runtime_language = language or self.language
        working_context = dict(context)
        outputs: dict[str, object] = {}
        for node in plan.ordered_nodes():
            result = runtime_language.execute_node(node, working_context)
            working_context.update(result)
            outputs.update(result)
            op_label = f"opcode {node.op_code}" if node.op_code is not None else "unknown_op"
            trace.record("execute", f"Executed {op_label}.", node_id=node.node_id, produced=list(result.keys()))
        return outputs

    @staticmethod
    def _score(outputs: dict[str, object], intent: PromptIntent, strategy: str) -> float:
        base = 0.5 if outputs else 0.0
        if "minimize_false_positives" in intent.constraints and strategy == "conservative":
            base += 0.3
        if outputs.get("emitted"):
            base += 0.2
        return base


class KernelOrchestrator:
    def __init__(self, kernel_factory: callable | None = None) -> None:
        self.kernel_factory = kernel_factory or SymKernel

    def converge(self, intent: PromptIntent, context: dict[str, object] | None = None) -> ConvergenceResult:
        strategies = ["default", "conservative"] if intent.goals == ["detect_stream_anomalies"] else ["default"]
        results = [self.kernel_factory().run(intent, context=context, strategy=strategy) for strategy in strategies]
        successful = [result for result in results if result.status == "success"]
        if successful:
            return max(successful, key=lambda result: result.score)
        return results[0]


def build_bundle(
    prompt: str,
    convergence: ConvergenceResult,
    compiler_meta: dict[str, object],
) -> ArtifactBundle:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return ArtifactBundle(
        run_id=f"run-{timestamp}",
        prompt=prompt,
        plan=convergence.plan,
        outputs=convergence.outputs,
        status=convergence.status,
        reason_codes=convergence.reason_codes,
        inventions=convergence.inventions,
        trace=convergence.trace,
        compiler=compiler_meta,
        language_snapshot=convergence.language_snapshot,
    )
