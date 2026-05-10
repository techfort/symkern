from __future__ import annotations

import argparse
import json
from pathlib import Path

from symkern.artifacts import ArtifactBundle, ArtifactStore
from symkern.intent_compiler import IntentCompiler
from symkern.kernel import KernelOrchestrator, SymKernel, build_bundle
from symkern.periscope import Periscope
from symkern.streaming import synthetic_anomaly_stream
from symkern.visualize import render_plan_graph


def _default_context_for_goals(goals: list[str]) -> dict[str, object] | None:
    if goals == ["detect_stream_anomalies"]:
        return {"events": synthetic_anomaly_stream()}
    return None


def _persist_bundle(bundle, artifact_root: str | Path) -> dict[str, object]:
    store = ArtifactStore(artifact_root)
    machine_code_path, dictionary_path = store.save_machine_code(bundle)
    bundle.files.update({"machine_code": str(machine_code_path), "machine_symbols": str(dictionary_path)})
    artifact_path = store.save_machine_artifact(bundle)
    report = Periscope().explain(bundle)
    periscope_path = store.save_periscope(bundle.run_id, report.render())
    bundle.files.update({"machine_artifact": str(artifact_path), "periscope": str(periscope_path)})
    artifact_path.write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")

    return {
        "run_id": bundle.run_id,
        "artifact_path": str(artifact_path),
        "machine_code_path": str(machine_code_path),
        "machine_symbols_path": str(dictionary_path),
        "language_path": str(machine_code_path),
        "periscope_path": str(periscope_path),
        "status": bundle.status,
        "plan_view": render_plan_graph(bundle.plan),
        "outputs": bundle.outputs,
    }


def submit_prompt(prompt: str, artifact_root: str | Path = "artifacts", context: dict[str, object] | None = None) -> dict[str, object]:
    compiler = IntentCompiler()
    compiler_result = compiler.compile(prompt)
    if context is None:
        context = _default_context_for_goals(compiler_result.intent.goals)

    orchestrator = KernelOrchestrator()
    convergence = orchestrator.converge(compiler_result.intent, context=context)
    bundle = build_bundle(
        prompt,
        convergence,
        compiler_meta={
            "translator": compiler_result.translator,
            "confidence": compiler_result.confidence,
            "assumptions": compiler_result.assumptions,
            "missing_information": compiler_result.missing_information,
        },
    )
    return _persist_bundle(bundle, artifact_root)


def replay_language(language_path: str | Path, artifact_root: str | Path = "artifacts", context: dict[str, object] | None = None) -> dict[str, object]:
    store = ArtifactStore(artifact_root)
    language_document = store.load_machine_language(language_path)
    goals = list(
        language_document.get("plan_metadata", {}).get(
            "goals",
            language_document.get("plan", {}).get("metadata", {}).get("goals", []),
        )
    )
    if context is None:
        context = _default_context_for_goals(goals)

    convergence = SymKernel().replay_language(language_document, context=context)
    bundle = build_bundle(
        prompt=f"replay:{Path(language_path)}",
        convergence=convergence,
        compiler_meta={
            "translator": "replay",
            "confidence": 1.0,
            "assumptions": ["replayed from persisted machine language"],
            "missing_information": [],
            "source_language": str(language_path),
        },
    )
    result = _persist_bundle(bundle, artifact_root)
    result["source_language_path"] = str(language_path)
    return result


def explain_machine_code(language_path: str | Path, artifact_root: str | Path = "artifacts", context: dict[str, object] | None = None) -> dict[str, object]:
    store = ArtifactStore(artifact_root)
    language_document = store.load_machine_language(language_path)
    goals = list(
        language_document.get("plan_metadata", {}).get(
            "goals",
            language_document.get("plan", {}).get("metadata", {}).get("goals", []),
        )
    )
    if context is None:
        context = _default_context_for_goals(goals)

    convergence = SymKernel().replay_language(language_document, context=context)
    run_id = f"explain-{Path(language_path).stem}"
    bundle = ArtifactBundle(
        run_id=run_id,
        prompt=f"explain:{Path(language_path)}",
        plan=convergence.plan,
        outputs=convergence.outputs,
        status=convergence.status,
        reason_codes=convergence.reason_codes,
        inventions=convergence.inventions,
        trace=convergence.trace,
        compiler={
            "translator": "periscope",
            "confidence": 1.0,
            "assumptions": ["explained from executable machine code"],
            "missing_information": [],
            "source_language": str(language_path),
        },
        language_snapshot=convergence.language_snapshot,
    )
    report = Periscope().explain(bundle)
    periscope_path = store.save_periscope(run_id, report.render())
    return {"periscope_path": str(periscope_path), "status": convergence.status, "source_language_path": str(language_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a prompt into a Symkern machine artifact.")
    command_group = parser.add_mutually_exclusive_group(required=True)
    command_group.add_argument("--prompt", help="Natural-language or symbolic prompt")
    command_group.add_argument("--replay-language", help="Path to a persisted machine_language.json file")
    command_group.add_argument("--explain-machine-code", help="Path to a persisted machine_code.bin or legacy machine_language.json file")
    parser.add_argument("--artifact-root", default="artifacts", help="Directory for run artifacts")
    args = parser.parse_args()
    if args.explain_machine_code:
        result = explain_machine_code(args.explain_machine_code, artifact_root=args.artifact_root)
        print(f"source-language: {result['source_language_path']}")
        print(f"status: {result['status']}")
        print(f"periscope: {result['periscope_path']}")
        return
    if args.replay_language:
        result = replay_language(args.replay_language, artifact_root=args.artifact_root)
        print(f"source-language: {result['source_language_path']}")
    else:
        result = submit_prompt(args.prompt, artifact_root=args.artifact_root)
    print(f"status: {result['status']}")
    print(f"machine-code: {result['machine_code_path']}")
    print(f"machine-symbols: {result['machine_symbols_path']}")
    print(f"artifact: {result['artifact_path']}")
    print(f"periscope: {result['periscope_path']}")
    print(result["plan_view"])


if __name__ == "__main__":
    main()
