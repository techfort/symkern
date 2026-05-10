from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from symkern.machine_language import MachineLanguage
from symkern.nodes import PlanGraph
from symkern.skills import SkillRegistry


@dataclass(slots=True)
class BackendCandidate:
    target: str
    slice_node_ids: list[str]
    estimated_interpreted_ns: int
    estimated_compiled_ns: int
    justification: str

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "slice_node_ids": list(self.slice_node_ids),
            "estimated_interpreted_ns": self.estimated_interpreted_ns,
            "estimated_compiled_ns": self.estimated_compiled_ns,
            "justification": self.justification,
        }


@dataclass(slots=True)
class BackendSelection:
    target: str
    slice_node_ids: list[str]
    estimated_interpreted_ns: int
    estimated_compiled_ns: int
    selection_reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "slice_node_ids": list(self.slice_node_ids),
            "estimated_interpreted_ns": self.estimated_interpreted_ns,
            "estimated_compiled_ns": self.estimated_compiled_ns,
            "selection_reason": self.selection_reason,
        }


@dataclass(slots=True)
class CompiledBackendResult:
    target: str
    outputs: dict[str, object]
    node_timings_ns: dict[str, int]
    total_ns: int
    generated_files: dict[str, str]


class CompiledBackendRegistry:
    GAUSSIAN_STATS_TARGET = "c.gaussian_array_statistics"
    WIKIPEDIA_DEATH_SELECTOR_TARGET = "c.wikipedia_death_selector"

    def __init__(self, repo_root: Path | None = None, skill_registry: SkillRegistry | None = None) -> None:
        self.repo_root = repo_root or Path(__file__).resolve().parents[2]
        self.skill_registry = skill_registry

    def assess_plan(self, plan: PlanGraph) -> tuple[list[BackendCandidate], BackendSelection | None]:
        ordered_nodes = plan.ordered_nodes()
        candidates: list[BackendCandidate] = []

        if len(ordered_nodes) >= 2 and [ordered_nodes[0].op_code, ordered_nodes[1].op_code] == [
            MachineLanguage.BUILTIN_OPCODES["core.generate_gaussian_array"],
            MachineLanguage.BUILTIN_OPCODES["core.compute_array_statistics"],
        ]:
            length = int(ordered_nodes[0].metadata.get("length", 20))
            interpreted_ns = 250_000 + (length * 55_000)
            compiled_ns = 90_000 + (length * 8_000)
            slice_signature = {
                "op_codes": [ordered_nodes[0].op_code, ordered_nodes[1].op_code],
                "goals": list(plan.metadata.get("goals", [])),
            }
            justification = "Gaussian array synthesis and statistics form a dense numeric slice that maps directly to a compiled backend."
            skill_match = self.skill_registry.lookup_backend_skill(self.GAUSSIAN_STATS_TARGET, slice_signature) if self.skill_registry is not None else None
            if skill_match is not None:
                compiled_ns = min(compiled_ns, int(skill_match.entry.get("mean_execute_ns", compiled_ns) or compiled_ns))
                justification += f" Local skill evidence available from {int(skill_match.entry.get('success_count', 0))} successful runs."
            candidates.append(
                BackendCandidate(
                    target=self.GAUSSIAN_STATS_TARGET,
                    slice_node_ids=[ordered_nodes[0].node_id, ordered_nodes[1].node_id],
                    estimated_interpreted_ns=interpreted_ns,
                    estimated_compiled_ns=compiled_ns,
                    justification=justification,
                )
            )

        election_node = next((node for node in ordered_nodes if node.op_code == MachineLanguage.BUILTIN_OPCODES["core.elect_illustrious_death"]), None)
        lookup_node = next((node for node in ordered_nodes if node.op_code == MachineLanguage.BUILTIN_OPCODES["core.lookup_wikipedia_deaths"]), None)
        if lookup_node is not None and election_node is not None:
            date_count = int(plan.state_bindings.get("date_count", 3) or 3)
            interpreted_ns = 180_000 + (date_count * 85_000)
            compiled_ns = 80_000 + (date_count * 20_000)
            slice_signature = {
                "op_codes": [election_node.op_code],
                "goals": list(plan.metadata.get("goals", [])),
            }
            justification = "Death-candidate ranking is a compact scoring-and-selection slice that can be lowered to compiled code."
            skill_match = self.skill_registry.lookup_backend_skill(self.WIKIPEDIA_DEATH_SELECTOR_TARGET, slice_signature) if self.skill_registry is not None else None
            if skill_match is not None:
                compiled_ns = min(compiled_ns, int(skill_match.entry.get("mean_execute_ns", compiled_ns) or compiled_ns))
                justification += f" Local skill evidence available from {int(skill_match.entry.get('success_count', 0))} successful runs."
            candidates.append(
                BackendCandidate(
                    target=self.WIKIPEDIA_DEATH_SELECTOR_TARGET,
                    slice_node_ids=[election_node.node_id],
                    estimated_interpreted_ns=interpreted_ns,
                    estimated_compiled_ns=compiled_ns,
                    justification=justification,
                )
            )

        selected: BackendSelection | None = None
        if candidates:
            best = min(candidates, key=lambda candidate: candidate.estimated_compiled_ns)
            if best.estimated_compiled_ns < best.estimated_interpreted_ns:
                selected = BackendSelection(
                    target=best.target,
                    slice_node_ids=list(best.slice_node_ids),
                    estimated_interpreted_ns=best.estimated_interpreted_ns,
                    estimated_compiled_ns=best.estimated_compiled_ns,
                    selection_reason="Selected the backend with the lowest estimated execution cost for the numeric slice.",
                )
        return candidates, selected

    def execute(self, plan: PlanGraph, selection: dict[str, object], context: dict[str, object] | None = None) -> CompiledBackendResult | None:
        target = str(selection.get("target", ""))
        if target == self.GAUSSIAN_STATS_TARGET:
            return self._execute_gaussian_statistics(plan, selection)
        if target == self.WIKIPEDIA_DEATH_SELECTOR_TARGET:
            return self._execute_wikipedia_death_selector(plan, selection, context)
        return None

    def _execute_gaussian_statistics(self, plan: PlanGraph, selection: dict[str, object]) -> CompiledBackendResult | None:
        target = str(selection.get("target", self.GAUSSIAN_STATS_TARGET))

        ordered_nodes = plan.ordered_nodes()
        slice_node_ids = list(selection.get("slice_node_ids", []))
        if len(slice_node_ids) != 2:
            return None

        node_map = {node.node_id: node for node in ordered_nodes}
        first_node = node_map.get(slice_node_ids[0])
        second_node = node_map.get(slice_node_ids[1])
        if first_node is None or second_node is None:
            return None

        generated_source_path = self._materialize_gaussian_source(plan, selection, first_node, second_node)
        binary_path = self._compile_gaussian_binary(generated_source_path)
        if binary_path is None:
            return None

        completed = subprocess.run(
            [
                str(binary_path),
                "--json",
                "--length",
                str(int(first_node.metadata.get("length", 20))),
                "--min",
                str(float(first_node.metadata.get("min_value", 0))),
                "--max",
                str(float(first_node.metadata.get("max_value", 20))),
                "--seed",
                str(int(plan.state_bindings.get("seed", 17))),
            ],
            check=True,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        timings = dict(payload.get("timings", {}))
        source_array = list(payload.get("source_array", []))
        statistics = dict(payload.get("statistics", {}))
        outputs = {
            "source_array": source_array,
            "statistics": statistics,
        }
        return CompiledBackendResult(
            target=target,
            outputs=outputs,
            node_timings_ns={
                first_node.node_id: int(timings.get("generate_ns", 0)),
                second_node.node_id: int(timings.get("statistics_ns", 0)),
            },
            total_ns=int(timings.get("total_ns", 0)),
            generated_files={
                "backend_source": str(generated_source_path),
                "backend_binary": str(binary_path),
            },
        )

    def _execute_wikipedia_death_selector(
        self,
        plan: PlanGraph,
        selection: dict[str, object],
        context: dict[str, object] | None,
    ) -> CompiledBackendResult | None:
        ordered_nodes = plan.ordered_nodes()
        slice_node_ids = list(selection.get("slice_node_ids", []))
        if len(slice_node_ids) != 1:
            return None
        node_map = {node.node_id: node for node in ordered_nodes}
        selection_node = node_map.get(slice_node_ids[0])
        if selection_node is None or context is None:
            return None

        features = list(context.get("death_candidate_features", []))
        if not features:
            return CompiledBackendResult(
                target=self.WIKIPEDIA_DEATH_SELECTOR_TARGET,
                outputs={"selected_death": {}},
                node_timings_ns={selection_node.node_id: 0},
                total_ns=0,
                generated_files={},
            )

        generated_source_path = self._materialize_selector_source(plan, selection, len(features))
        binary_path = self._compile_binary(generated_source_path)
        if binary_path is None:
            return None

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".tsv") as handle:
            input_path = Path(handle.name)
            for feature in features:
                safe_description = str(feature.get("description", "")).replace("\t", " ").replace("\n", " ")
                safe_url = str(feature.get("wikipedia_url", "")).replace("\t", " ").replace("\n", " ")
                handle.write(
                    "\t".join(
                        [
                            str(feature.get("candidate_id", "")),
                            str(feature.get("person", "")).replace("\t", " ").replace("\n", " "),
                            str(feature.get("date", "")),
                            str(int(feature.get("year", 0))),
                            safe_description,
                            safe_url,
                            str(int(feature.get("keyword_hits", 0))),
                            str(int(feature.get("description_length", 0))),
                            str(int(feature.get("page_count", 1))),
                            str(int(feature.get("era_bonus", 0))),
                        ]
                    )
                    + "\n"
                )

        try:
            completed = subprocess.run(
                [str(binary_path), "--json", "--input", str(input_path)],
                check=True,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
            )
        finally:
            input_path.unlink(missing_ok=True)

        payload = json.loads(completed.stdout)
        selected_death = dict(payload.get("selected_death", {}))
        selected_death["illustrious_score"] = int(payload.get("selected_death", {}).get("illustrious_score", 0))
        timings = dict(payload.get("timings", {}))
        return CompiledBackendResult(
            target=self.WIKIPEDIA_DEATH_SELECTOR_TARGET,
            outputs={"selected_death": selected_death},
            node_timings_ns={selection_node.node_id: int(timings.get("selection_ns", 0))},
            total_ns=int(timings.get("total_ns", 0)),
            generated_files={
                "backend_source": str(generated_source_path),
                "backend_binary": str(binary_path),
            },
        )

    def _materialize_gaussian_source(
        self,
        plan: PlanGraph,
        selection: dict[str, object],
        first_node,
        second_node,
    ) -> Path:
        template_path = self.repo_root / "benchmarks" / "gaussian_array_stats.c"
        generated_dir = self.repo_root / ".symkern" / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        generated_path = generated_dir / f"{str(selection.get('target', self.GAUSSIAN_STATS_TARGET)).replace('.', '_')}_{plan.plan_id}.c"
        header = (
            "/*\n"
            " Symkern generated backend artifact\n"
            f" target: {selection.get('target', self.GAUSSIAN_STATS_TARGET)}\n"
            f" slice_node_ids: {list(selection.get('slice_node_ids', []))}\n"
            f" length: {int(first_node.metadata.get('length', 20))}\n"
            f" min_value: {float(first_node.metadata.get('min_value', 0))}\n"
            f" max_value: {float(first_node.metadata.get('max_value', 20))}\n"
            f" requested_statistics: {list(second_node.metadata.get('requested_statistics', []))}\n"
            "*/\n\n"
        )
        content = header + template_path.read_text(encoding="utf-8")
        if not generated_path.exists() or generated_path.read_text(encoding="utf-8") != content:
            generated_path.write_text(content, encoding="utf-8")
        return generated_path

    def _materialize_selector_source(self, plan: PlanGraph, selection: dict[str, object], candidate_count: int) -> Path:
        template_path = self.repo_root / "benchmarks" / "illustrious_death_selector.c"
        generated_dir = self.repo_root / ".symkern" / "generated"
        generated_dir.mkdir(parents=True, exist_ok=True)
        generated_path = generated_dir / f"{str(selection.get('target', self.WIKIPEDIA_DEATH_SELECTOR_TARGET)).replace('.', '_')}_{plan.plan_id}.c"
        header = (
            "/*\n"
            " Symkern generated backend artifact\n"
            f" target: {selection.get('target', self.WIKIPEDIA_DEATH_SELECTOR_TARGET)}\n"
            f" slice_node_ids: {list(selection.get('slice_node_ids', []))}\n"
            f" candidate_count_hint: {candidate_count}\n"
            "*/\n\n"
        )
        content = header + template_path.read_text(encoding="utf-8")
        if not generated_path.exists() or generated_path.read_text(encoding="utf-8") != content:
            generated_path.write_text(content, encoding="utf-8")
        return generated_path

    def _compile_gaussian_binary(self, source_path: Path) -> Path | None:
        return self._compile_binary(source_path)

    def _compile_binary(self, source_path: Path) -> Path | None:
        binary_path = self.repo_root / ".symkern" / "bin" / f"{source_path.stem}"
        if binary_path.exists() and binary_path.stat().st_mtime_ns >= source_path.stat().st_mtime_ns:
            return binary_path

        compiler = shutil.which("gcc") or shutil.which("cc")
        if compiler is None:
            return None

        binary_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [compiler, "-O3", "-std=c11", str(source_path), "-lm", "-o", str(binary_path)],
            check=True,
            cwd=self.repo_root,
        )
        return binary_path