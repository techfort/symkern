from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import perf_counter_ns

from symkern.artifacts import ArtifactBundle, ArtifactStore
from symkern.intent_compiler import IntentCompiler
from symkern.translator import AnthropicTranslatorAdapter, OllamaTranslatorAdapter, OpenAICompatibleTranslatorAdapter, resolve_api_key
from symkern.kernel import KernelOrchestrator, SymKernel, build_bundle
from symkern.periscope import Periscope
from symkern.skills import SkillRegistry
from symkern.streaming import synthetic_anomaly_stream
from symkern.visualize import render_plan_graph


def _default_context_for_goals(goals: list[str]) -> dict[str, object] | None:
    if goals == ["detect_stream_anomalies"]:
        return {"events": synthetic_anomaly_stream()}
    return None


def _deployment_root_for_artifact_root(artifact_root: str | Path) -> Path:
    root = Path(artifact_root)
    return root.parent if root.name == "artifacts" else root


def _update_skill_registry(bundle: ArtifactBundle, artifact_root: str | Path) -> dict[str, object] | None:
    selection = dict(bundle.backend.get("selection", {}))
    target = str(selection.get("target", ""))
    deployment_root = _deployment_root_for_artifact_root(artifact_root)
    registry = SkillRegistry(deployment_root)
    registry_summary = registry.reconcile_executable_references()
    bundle.backend["skill_registry"] = {
        "registry_path": str(registry.registry_path),
        "retired_skill_ids": list(registry_summary.get("retired_skill_ids", [])),
        "skill_count": int(registry_summary.get("skill_count", 0)),
    }
    executable_path = str(bundle.files.get("machine_code", ""))
    abstraction_skills = []
    for invention in bundle.inventions:
        abstraction_entry = registry.record_abstraction_skill(
            invention=dict(invention),
            run_id=bundle.run_id,
            prompt=bundle.prompt,
            executable_path=executable_path,
        )
        abstraction_skills.append(
            {
                "skill_id": abstraction_entry["skill_id"],
                "op_code": abstraction_entry["op_code"],
                "status": abstraction_entry["status"],
                "application_count": abstraction_entry["application_count"],
                "active_reference_count": abstraction_entry["active_reference_count"],
            }
        )
    if abstraction_skills:
        bundle.backend["skill_registry"]["abstractions"] = abstraction_skills
    if not target:
        return None

    slice_signature = {
        "op_codes": [node.op_code for node in bundle.plan.ordered_nodes() if node.node_id in list(selection.get("slice_node_ids", [])) and node.op_code is not None],
        "goals": list(bundle.plan.metadata.get("goals", [])),
    }
    skill_entry = registry.record_backend_skill(
        target=target,
        slice_signature=slice_signature,
        ideal_for=list(bundle.plan.metadata.get("goals", [])),
        selection=selection,
        timings=bundle.timings,
        backend=bundle.backend,
        run_id=bundle.run_id,
        prompt=bundle.prompt,
        executable_path=executable_path,
        success=bundle.status == "success",
    )
    bundle.backend["skill"] = {
        "skill_id": skill_entry["skill_id"],
        "registry_path": str(registry.registry_path),
        "status": skill_entry["status"],
        "success_count": skill_entry["success_count"],
        "selection_count": skill_entry["selection_count"],
        "active_reference_count": skill_entry["active_reference_count"],
    }
    return bundle.backend["skill"]


def _persist_bundle(bundle, artifact_root: str | Path) -> dict[str, object]:
    store = ArtifactStore(artifact_root)
    persist_start_ns = perf_counter_ns()

    backend_write_start_ns = perf_counter_ns()
    backend_files = store.save_backend_artifacts(bundle)
    bundle.timings["persist_backend_artifacts_ns"] = perf_counter_ns() - backend_write_start_ns
    if backend_files:
        bundle.backend["artifacts"] = dict(backend_files)
        bundle.files.update(dict(backend_files))

    machine_code_start_ns = perf_counter_ns()
    machine_code_path, dictionary_path = store.save_machine_code(bundle)
    bundle.timings["persist_machine_code_ns"] = perf_counter_ns() - machine_code_start_ns
    bundle.files.update({"machine_code": str(machine_code_path), "machine_symbols": str(dictionary_path)})

    artifact_write_start_ns = perf_counter_ns()
    artifact_path = store.save_machine_artifact(bundle)
    bundle.timings["persist_artifact_initial_ns"] = perf_counter_ns() - artifact_write_start_ns

    periscope_render_start_ns = perf_counter_ns()
    report = Periscope().explain(bundle)
    rendered_report = report.render()
    bundle.timings["persist_periscope_render_ns"] = perf_counter_ns() - periscope_render_start_ns
    periscope_write_start_ns = perf_counter_ns()
    periscope_path = store.save_periscope(bundle.run_id, rendered_report)
    bundle.timings["persist_periscope_ns"] = perf_counter_ns() - periscope_write_start_ns
    bundle.files.update({"machine_artifact": str(artifact_path), "periscope": str(periscope_path)})

    artifact_rewrite_start_ns = perf_counter_ns()
    bundle.timings["persist_total_ns"] = perf_counter_ns() - persist_start_ns
    artifact_path.write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
    bundle.timings["persist_artifact_final_ns"] = perf_counter_ns() - artifact_rewrite_start_ns
    bundle.timings["persist_total_ns"] = perf_counter_ns() - persist_start_ns

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
        "timings": dict(bundle.timings),
        "backend": dict(bundle.backend),
    }


def submit_prompt(
    prompt: str,
    artifact_root: str | Path = "artifacts",
    context: dict[str, object] | None = None,
    translator: str = "heuristic",
    ollama_model: str | None = None,
    translator_model: str | None = None,
    translator_endpoint: str | None = None,
    translator_api_key: str | None = None,
    translator_api_key_env: str | None = None,
) -> dict[str, object]:
    submit_start_ns = perf_counter_ns()
    translator_adapter = None
    if translator == "ollama":
        model = ollama_model or translator_model
        if not model:
            raise ValueError("ollama_model is required when translator='ollama'")
        translator_adapter = OllamaTranslatorAdapter(model=model, endpoint=translator_endpoint or "http://localhost:11434/api/generate")
    if translator == "openai-compatible":
        if not translator_model:
            raise ValueError("translator_model is required when translator='openai-compatible'")
        translator_adapter = OpenAICompatibleTranslatorAdapter(
            model=translator_model,
            endpoint=translator_endpoint or "https://api.openai.com/v1/chat/completions",
            api_key=resolve_api_key(translator_api_key, translator_api_key_env),
        )
    if translator == "anthropic":
        if not translator_model:
            raise ValueError("translator_model is required when translator='anthropic'")
        translator_adapter = AnthropicTranslatorAdapter(
            model=translator_model,
            endpoint=translator_endpoint or "https://api.anthropic.com/v1/messages",
            api_key=resolve_api_key(translator_api_key, translator_api_key_env),
        )
    compiler = IntentCompiler(translator_adapter=translator_adapter)
    compile_start_ns = perf_counter_ns()
    compiler_result = compiler.compile(prompt)
    compile_ns = perf_counter_ns() - compile_start_ns
    if context is None:
        context = _default_context_for_goals(compiler_result.intent.goals)

    deployment_root = _deployment_root_for_artifact_root(artifact_root)
    skill_registry = SkillRegistry(deployment_root)
    orchestrator = KernelOrchestrator(kernel_factory=lambda: SymKernel(skill_registry=skill_registry))
    converge_start_ns = perf_counter_ns()
    convergence = orchestrator.converge(compiler_result.intent, context=context)
    converge_ns = perf_counter_ns() - converge_start_ns
    bundle_timings = {
        **dict(convergence.timings),
        "compile_ns": compile_ns,
        "converge_ns": converge_ns,
    }
    bundle = build_bundle(
        prompt,
        convergence,
        compiler_meta={
            "translator": compiler_result.translator,
            "confidence": compiler_result.confidence,
            "assumptions": compiler_result.assumptions,
            "missing_information": compiler_result.missing_information,
        },
        timings=bundle_timings,
    )
    result = _persist_bundle(bundle, artifact_root)
    _update_skill_registry(bundle, artifact_root)
    bundle.timings["submit_total_ns"] = perf_counter_ns() - submit_start_ns
    Path(result["artifact_path"]).write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
    result["timings"] = dict(bundle.timings)
    result["backend"] = dict(bundle.backend)
    return result


def replay_language(language_path: str | Path, artifact_root: str | Path = "artifacts", context: dict[str, object] | None = None) -> dict[str, object]:
    store = ArtifactStore(artifact_root)
    replay_start_ns = perf_counter_ns()
    load_start_ns = perf_counter_ns()
    language_document = store.load_machine_language(language_path)
    load_ns = perf_counter_ns() - load_start_ns
    goals = list(
        language_document.get("plan_metadata", {}).get(
            "goals",
            language_document.get("plan", {}).get("metadata", {}).get("goals", []),
        )
    )
    if context is None:
        context = _default_context_for_goals(goals)

    replay_kernel_start_ns = perf_counter_ns()
    deployment_root = _deployment_root_for_artifact_root(artifact_root)
    skill_registry = SkillRegistry(deployment_root)
    convergence = SymKernel(skill_registry=skill_registry).replay_language(language_document, context=context)
    replay_kernel_ns = perf_counter_ns() - replay_kernel_start_ns
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
        timings={
            **dict(convergence.timings),
            "load_machine_language_ns": load_ns,
            "replay_ns": replay_kernel_ns,
        },
    )
    result = _persist_bundle(bundle, artifact_root)
    _update_skill_registry(bundle, artifact_root)
    bundle.timings["replay_total_ns"] = perf_counter_ns() - replay_start_ns
    Path(result["artifact_path"]).write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
    result["source_language_path"] = str(language_path)
    result["timings"] = dict(bundle.timings)
    result["backend"] = dict(bundle.backend)
    return result


def explain_machine_code(language_path: str | Path, artifact_root: str | Path = "artifacts", context: dict[str, object] | None = None) -> dict[str, object]:
    store = ArtifactStore(artifact_root)
    explain_start_ns = perf_counter_ns()
    load_start_ns = perf_counter_ns()
    language_document = store.load_machine_language(language_path)
    load_ns = perf_counter_ns() - load_start_ns
    goals = list(
        language_document.get("plan_metadata", {}).get(
            "goals",
            language_document.get("plan", {}).get("metadata", {}).get("goals", []),
        )
    )
    if context is None:
        context = _default_context_for_goals(goals)

    replay_start_ns = perf_counter_ns()
    convergence = SymKernel().replay_language(language_document, context=context)
    replay_ns = perf_counter_ns() - replay_start_ns
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
        timings={
            **dict(convergence.timings),
            "load_machine_language_ns": load_ns,
            "explain_replay_ns": replay_ns,
        },
    )
    periscope_start_ns = perf_counter_ns()
    report = Periscope().explain(bundle)
    rendered_report = report.render()
    bundle.timings["explain_render_ns"] = perf_counter_ns() - periscope_start_ns
    write_start_ns = perf_counter_ns()
    periscope_path = store.save_periscope(run_id, rendered_report)
    bundle.timings["explain_write_ns"] = perf_counter_ns() - write_start_ns
    bundle.timings["explain_total_ns"] = perf_counter_ns() - explain_start_ns
    report = Periscope().explain(bundle)
    periscope_path.write_text(report.render(), encoding="utf-8")
    return {
        "periscope_path": str(periscope_path),
        "status": convergence.status,
        "source_language_path": str(language_path),
        "timings": dict(bundle.timings),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile a prompt into a Symkern machine artifact.")
    command_group = parser.add_mutually_exclusive_group(required=True)
    command_group.add_argument("--prompt", help="Natural-language or symbolic prompt")
    command_group.add_argument("--replay-language", help="Path to a persisted machine_language.json file")
    command_group.add_argument("--explain-machine-code", help="Path to a persisted machine_code.bin or legacy machine_language.json file")
    parser.add_argument("--artifact-root", default="artifacts", help="Directory for run artifacts")
    parser.add_argument("--translator", choices=["heuristic", "ollama", "openai-compatible", "anthropic"], default="heuristic", help="Ingress translator to use")
    parser.add_argument("--ollama-model", help="Ollama model name for translator=ollama")
    parser.add_argument("--translator-model", help="Model name for non-heuristic translators")
    parser.add_argument("--translator-endpoint", help="Override the translator HTTP endpoint")
    parser.add_argument("--translator-api-key", help="API key for remote translator providers")
    parser.add_argument("--translator-api-key-env", help="Environment variable to read the translator API key from")
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
        result = submit_prompt(
            args.prompt,
            artifact_root=args.artifact_root,
            translator=args.translator,
            ollama_model=args.ollama_model,
            translator_model=args.translator_model,
            translator_endpoint=args.translator_endpoint,
            translator_api_key=args.translator_api_key,
            translator_api_key_env=args.translator_api_key_env,
        )
    print(f"status: {result['status']}")
    print(f"machine-code: {result['machine_code_path']}")
    print(f"machine-symbols: {result['machine_symbols_path']}")
    print(f"artifact: {result['artifact_path']}")
    print(f"periscope: {result['periscope_path']}")
    print(result["plan_view"])


if __name__ == "__main__":
    main()
