from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns

from symkern.artifacts import ArtifactBundle, ArtifactStore
from symkern.intent_compiler import IntentCompiler
from symkern.kernel import ConvergenceResult
from symkern.logging import ExecutionTrace
from symkern.program_spec_contract import build_translator_context_bundle
from symkern.programs import ProgramRegistry
from symkern.prompt_layer import ProgramSpec, ProgramSpecValidator
from symkern.translator import AnthropicTranslatorAdapter, OllamaTranslatorAdapter, OpenAICompatibleTranslatorAdapter, resolve_api_key
from symkern.kernel import KernelOrchestrator, SymKernel, build_bundle
from symkern.nodes import PlanGraph
from symkern.periscope import Periscope
from symkern.skills import SkillRegistry
from symkern.streaming import synthetic_anomaly_stream
from symkern.visualize import render_plan_graph
from symkern.operator_synthesis_contract import parse_synthesis_response, OperatorCompositionSpec, OperatorHandlerSpec
from symkern.operator_compiler import compile_handler, validate_handler


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


def _register_program_id(result: dict[str, object], bundle: ArtifactBundle, artifact_root: str | Path) -> dict[str, object] | None:
    program_id = str(bundle.program_spec.get("program_id", "")).strip()
    if not program_id or not result.get("machine_code_path"):
        return None
    deployment_root = _deployment_root_for_artifact_root(artifact_root)
    entry = ProgramRegistry(deployment_root).register(
        program_id=program_id,
        machine_code_path=str(result["machine_code_path"]),
        machine_symbols_path=str(result.get("machine_symbols_path")) if result.get("machine_symbols_path") else None,
        artifact_path=str(result["artifact_path"]),
        program_spec=dict(bundle.program_spec),
        input_contract=list(bundle.input_contract),
    )
    result["program_id"] = program_id
    result["program_registry"] = {"registry_path": str(ProgramRegistry(deployment_root).registry_path), "entry": entry}
    return entry


def _persist_bundle(bundle, artifact_root: str | Path) -> dict[str, object]:
    store = ArtifactStore(artifact_root)
    persist_start_ns = perf_counter_ns()

    machine_code_path: Path | None = None
    dictionary_path: Path | None = None
    if bundle.status in {"success", "created"}:
        backend_write_start_ns = perf_counter_ns()
        backend_files = store.save_backend_artifacts(bundle) if bundle.status == "success" else {}
        bundle.timings["persist_backend_artifacts_ns"] = perf_counter_ns() - backend_write_start_ns
        if backend_files:
            bundle.backend["artifacts"] = dict(backend_files)
            bundle.files.update(dict(backend_files))

        machine_code_start_ns = perf_counter_ns()
        machine_code_path, dictionary_path = store.save_machine_code(bundle)
        bundle.timings["persist_machine_code_ns"] = perf_counter_ns() - machine_code_start_ns
        bundle.files.update({"machine_code": str(machine_code_path), "machine_symbols": str(dictionary_path)})
    else:
        bundle.timings["persist_backend_artifacts_ns"] = 0
        bundle.timings["persist_machine_code_ns"] = 0

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
        "machine_code_path": str(machine_code_path) if machine_code_path is not None else None,
        "machine_symbols_path": str(dictionary_path) if dictionary_path is not None else None,
        "language_path": str(machine_code_path) if machine_code_path is not None else None,
        "periscope_path": str(periscope_path),
        "status": bundle.status,
        "plan_view": render_plan_graph(bundle.plan),
        "outputs": bundle.outputs,
        "timings": dict(bundle.timings),
        "backend": dict(bundle.backend),
        "input_contract": list(bundle.input_contract),
        "program_spec": dict(bundle.program_spec),
    }


def _blocking_synthesis_gaps(program_spec: dict[str, object]) -> list[dict[str, object]]:
    return [dict(gap) for gap in list(program_spec.get("synthesis_gaps", [])) if str(gap.get("severity", "blocking")) == "blocking"]


def _build_creation_failure_bundle(
    prompt: str,
    compiler_result,
    timings: dict[str, object],
) -> ArtifactBundle:
    trace = ExecutionTrace()
    trace.record("compile", "Intent compiled into a machine plan request.", goals=compiler_result.intent.goals)
    blocking_gaps = _blocking_synthesis_gaps(compiler_result.program_spec.to_dict())
    for gap in blocking_gaps:
        trace.record(
            "validate",
            f"Blocked program creation due to {gap.get('reason', 'unknown')}.",
            stage_id=gap.get("stage_id", "unknown"),
            reason=gap.get("reason", "unknown"),
        )
    return ArtifactBundle(
        run_id=f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}",
        prompt=prompt,
        plan=PlanGraph(plan_id="plan-creation-failed", metadata={"goals": list(compiler_result.intent.goals), "strategy": "creation_failed"}),
        outputs={},
        status="failed",
        reason_codes=["synthesis_failed", *[str(gap.get("reason", "unknown")) for gap in blocking_gaps]],
        trace=trace,
        compiler={
            "translator": compiler_result.translator,
            "confidence": compiler_result.confidence,
            "assumptions": compiler_result.assumptions,
            "missing_information": compiler_result.missing_information,
        },
        timings=dict(timings),
        program_spec=compiler_result.program_spec.to_dict(),
        synthesis_validation={
            "status": "failed",
            "failures": blocking_gaps,
        },
    )


def _build_program_spec_failure_bundle(
    prompt: str,
    program_spec: ProgramSpec,
    translator_label: str,
    timings: dict[str, object],
    reason: str,
    notes: str,
) -> ArtifactBundle:
    trace = ExecutionTrace()
    trace.record("compile", "ProgramSpec authored from prompt.", program_id=program_spec.program_id or "")
    trace.record("validate", f"Blocked program creation due to {reason}.", stage_id="program_spec_validation", reason=reason)
    gap = {
        "gap_id": f"gap-{reason}",
        "stage_id": "program_spec_validation",
        "reason": reason,
        "severity": "blocking",
        "requested_capability": prompt,
        "notes": notes,
    }
    program_spec.synthesis_gaps.append(gap)
    return ArtifactBundle(
        run_id=f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}",
        prompt=prompt,
        plan=PlanGraph(plan_id="plan-creation-failed", metadata={"program_id": program_spec.program_id, "strategy": "creation_failed"}),
        outputs={},
        status="failed",
        reason_codes=["synthesis_failed", reason],
        trace=trace,
        compiler={
            "translator": translator_label,
            "confidence": program_spec.confidence,
            "assumptions": list(program_spec.assumptions),
            "missing_information": list(program_spec.missing_information),
        },
        timings=dict(timings),
        program_spec=program_spec.to_dict(),
        synthesis_validation={"status": "failed", "failures": [gap]},
    )


def _translate_prompt_to_program_spec(prompt: str, translator_adapter, program_id: str | None = None) -> ProgramSpec:
    validator = ProgramSpecValidator()
    translated = translator_adapter.translate_program_spec(prompt)
    try:
        program_spec = validator.validate(ProgramSpec.from_dict(translated.payload))
    except ValueError as error:
        repaired = translator_adapter.repair_program_spec(prompt, translated.payload, str(error))
        program_spec = validator.validate(ProgramSpec.from_dict(repaired.payload))
        translated = repaired
    if program_id and not program_spec.program_id:
        program_spec.program_id = str(program_id).strip() or None
    program_spec.translator_metadata.setdefault("translator", translated.translator)
    program_spec.translator_metadata.setdefault("source", "prompt")
    if not program_spec.title:
        program_spec.title = prompt.strip()
    return program_spec


def _load_input_payload(input_json: str | None = None, input_file: str | None = None) -> dict[str, object] | None:
    if input_json and input_file:
        raise ValueError("Only one of input_json or input_file may be provided")
    if input_json:
        payload = json.loads(input_json)
    elif input_file:
        payload = json.loads(Path(input_file).read_text(encoding="utf-8"))
    else:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Invocation input payload must be a JSON object")
    return dict(payload)


def _load_program_spec_payload(program_spec_file: str | None = None, program_spec_json: str | None = None) -> ProgramSpec | None:
    if program_spec_file and program_spec_json:
        raise ValueError("Only one of program_spec_file or program_spec_json may be provided")
    if program_spec_file:
        payload = json.loads(Path(program_spec_file).read_text(encoding="utf-8"))
    elif program_spec_json:
        payload = json.loads(program_spec_json)
    else:
        return None
    if not isinstance(payload, dict):
        raise ValueError("ProgramSpec payload must be a JSON object")
    return ProgramSpecValidator().validate(ProgramSpec.from_dict(payload))


def _validate_invocation_inputs(language_document: dict[str, object], input_payload: dict[str, object] | None) -> dict[str, object] | None:
    if input_payload is None:
        return None
    plan_metadata = dict(language_document.get("plan_metadata", language_document.get("plan", {}).get("metadata", {})))
    input_contract = list(plan_metadata.get("input_contract", []))
    contract_by_name = {str(item.get("name", "")): dict(item) for item in input_contract}
    for name, value in input_payload.items():
        if name not in contract_by_name:
            raise ValueError(f"Input '{name}' is not declared by this program's input contract")
        contract = contract_by_name[name]
        kind = str(contract.get("kind", ""))
        constraints = dict(contract.get("constraints", {}))
        if kind in {"array[integer]", "array[number]", "array[historical_date]"}:
            if not isinstance(value, list):
                raise ValueError(f"Input '{name}' must be a JSON array")
            expected_length = constraints.get("expected_length")
            if expected_length is not None and len(value) != int(expected_length):
                raise ValueError(f"Input '{name}' must contain exactly {int(expected_length)} items")
            if kind == "array[integer]" and any(not isinstance(item, int) for item in value):
                raise ValueError(f"Input '{name}' must contain integers")
            if kind == "array[number]" and any(not isinstance(item, (int, float)) for item in value):
                raise ValueError(f"Input '{name}' must contain numeric values")
            if kind in {"array[integer]", "array[number]"}:
                min_value = constraints.get("min_value")
                max_value = constraints.get("max_value")
                if min_value is not None and any(float(item) < float(min_value) for item in value):
                    raise ValueError(f"Input '{name}' contains values below the declared minimum")
                if max_value is not None and any(float(item) > float(max_value) for item in value):
                    raise ValueError(f"Input '{name}' contains values above the declared maximum")
        if kind == "event_stream" and not isinstance(value, list):
            raise ValueError(f"Input '{name}' must be a JSON array of event objects")
    return dict(input_payload)


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
    program_id: str | None = None,
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
    if translator_adapter is not None:
        compile_start_ns = perf_counter_ns()
        try:
            program_spec = _translate_prompt_to_program_spec(prompt, translator_adapter, program_id=program_id)
        except ValueError as error:
            bundle = _build_program_spec_failure_bundle(
                prompt=prompt,
                program_spec=ProgramSpec(
                    program_id=program_id,
                    title=prompt,
                    requested_inputs=[],
                    requested_outputs=[{"name": "emitted", "kind": "opaque"}],
                    transformations=[{"stage_id": "program_spec_translation", "kind": "translation_failed", "inputs": [], "outputs": [{"name": "emitted"}], "blocking": True}],
                ),
                translator_label=f"{translator}:{ollama_model or translator_model or ''}".rstrip(":"),
                timings={"compile_ns": perf_counter_ns() - compile_start_ns},
                reason="program_spec_translation_failed",
                notes=str(error),
            )
            result = _persist_bundle(bundle, artifact_root)
            bundle.timings["submit_total_ns"] = perf_counter_ns() - submit_start_ns
            Path(result["artifact_path"]).write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
            result["timings"] = dict(bundle.timings)
            result["backend"] = dict(bundle.backend)
            result["program_spec"] = dict(bundle.program_spec)
            return result
        return submit_program_spec(program_spec, artifact_root=artifact_root, context=context, program_id=program_id, source_prompt=prompt, translator_adapter=translator_adapter)
    compiler = IntentCompiler(translator_adapter=translator_adapter)
    compile_start_ns = perf_counter_ns()
    compiler_result = compiler.compile(prompt)
    compile_ns = perf_counter_ns() - compile_start_ns
    if _blocking_synthesis_gaps(compiler_result.program_spec.to_dict()):
        bundle = _build_creation_failure_bundle(
            prompt,
            compiler_result,
            timings={
                "compile_ns": compile_ns,
            },
        )
        result = _persist_bundle(bundle, artifact_root)
        bundle.timings["submit_total_ns"] = perf_counter_ns() - submit_start_ns
        Path(result["artifact_path"]).write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
        result["timings"] = dict(bundle.timings)
        result["backend"] = dict(bundle.backend)
        result["program_spec"] = dict(bundle.program_spec)
        return result
    if context is None:
        context = _default_context_for_goals(compiler_result.intent.goals)

    deployment_root = _deployment_root_for_artifact_root(artifact_root)
    skill_registry = SkillRegistry(deployment_root)
    orchestrator = KernelOrchestrator(kernel_factory=lambda: SymKernel(skill_registry=skill_registry, deployment_root=deployment_root))
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
        program_spec=compiler_result.program_spec.to_dict(),
        synthesis_validation={"status": "success", "failures": []},
    )
    result = _persist_bundle(bundle, artifact_root)
    _update_skill_registry(bundle, artifact_root)
    _register_program_id(result, bundle, artifact_root)
    bundle.timings["submit_total_ns"] = perf_counter_ns() - submit_start_ns
    Path(result["artifact_path"]).write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
    result["timings"] = dict(bundle.timings)
    result["backend"] = dict(bundle.backend)
    result["program_spec"] = dict(bundle.program_spec)
    return result


def _register_synthesized_operator(language, synthesis_spec, deployment_root: Path) -> None:
    """Register a synthesized operator from a composition or handler_spec LLM response."""
    from symkern.machine_language import OperationSchema

    if isinstance(synthesis_spec, OperatorCompositionSpec):
        # Tier 1: chain of existing operators
        op_id_to_schema = {s.op_id: s for s in language.op_registry_by_code.values() if s.op_id}
        step_ids = [str(step.get("operator_id", "")) for step in synthesis_spec.steps]
        missing = [sid for sid in step_ids if sid not in op_id_to_schema]
        if missing:
            raise ValueError(f"Composition references unknown operators: {missing}")
        opcodes = [op_id_to_schema[sid].op_code for sid in step_ids]
        handler = language._build_invented_handler(opcodes)
        op_code = language.allocate_invented_opcode()
        schema = OperationSchema(
            op_id=synthesis_spec.operator_id,
            op_code=op_code,
            description=synthesis_spec.description,
            signature={"inputs": synthesis_spec.inputs, "outputs": synthesis_spec.outputs},
            machine_metadata={"invented_from_opcodes": opcodes},
            handler=handler,
        )
        language.register(schema)
        language.persist_synthesized_operator(
            op_id=synthesis_spec.operator_id,
            op_code=op_code,
            signature={"inputs": synthesis_spec.inputs, "outputs": synthesis_spec.outputs},
            machine_metadata={"invented_from_opcodes": opcodes},
            description=synthesis_spec.description,
            implementation_kind="composition",
            implementation_payload={"composition_steps": synthesis_spec.steps},
        )

    elif isinstance(synthesis_spec, OperatorHandlerSpec):
        # Tier 2: algorithm_steps -> compiled Python handler
        handler = compile_handler(synthesis_spec)
        validate_handler(handler, synthesis_spec)
        op_code = language.allocate_invented_opcode()
        schema = OperationSchema(
            op_id=synthesis_spec.operator_id,
            op_code=op_code,
            description=synthesis_spec.description,
            signature={"inputs": synthesis_spec.inputs, "outputs": synthesis_spec.outputs},
            machine_metadata={},
            handler=handler,
        )
        language.register(schema)
        language.persist_synthesized_operator(
            op_id=synthesis_spec.operator_id,
            op_code=op_code,
            signature={"inputs": synthesis_spec.inputs, "outputs": synthesis_spec.outputs},
            machine_metadata={},
            description=synthesis_spec.description,
            implementation_kind="handler_spec",
            implementation_payload={"algorithm_steps": synthesis_spec.algorithm_steps},
        )

    else:
        raise ValueError(f"Unrecognised synthesis spec type: {type(synthesis_spec).__name__}")


def submit_program_spec(
    program_spec: ProgramSpec,
    artifact_root: str | Path = "artifacts",
    context: dict[str, object] | None = None,
    program_id: str | None = None,
    source_prompt: str | None = None,
    translator_adapter=None,
) -> dict[str, object]:
    submit_start_ns = perf_counter_ns()
    validated_spec = ProgramSpecValidator().validate(program_spec)
    if program_id:
        validated_spec.program_id = str(program_id).strip() or validated_spec.program_id
    deployment_root = _deployment_root_for_artifact_root(artifact_root)
    language = SymKernel(deployment_root=deployment_root).language
    compile_start_ns = perf_counter_ns()

    # --- Synthesis loop: attempt operator synthesis for missing ops (max 3 rounds) ---
    for synthesis_round in range(3):
        assembly = language.assemble_plan_from_program_spec(validated_spec)
        if not assembly.gaps:
            break
        if translator_adapter is None:
            # No LLM available — fall through to fail-closed path
            break
        existing_ids = [s.op_id for s in language.op_registry_by_code.values() if s.op_id]
        unresolvable: list[str] = []
        for gap in assembly.gaps:
            if not gap.operator_id:
                unresolvable.append("<missing operator_id>")
                continue
            try:
                envelope = translator_adapter.synthesize_operator(
                    gap.operator_id,
                    existing_ids,
                )
                synthesis_spec = parse_synthesis_response(envelope.payload)
            except Exception as err:
                unresolvable.append(f"{gap.operator_id}: synthesis request failed ({err})")
                continue

            try:
                _register_synthesized_operator(language, synthesis_spec, deployment_root)
            except Exception as err:
                unresolvable.append(f"{gap.operator_id}: registration failed ({err})")
                continue

        if unresolvable:
            # At least one op could not be synthesized — fail closed
            error_notes = "; ".join(unresolvable)
            bundle = _build_program_spec_failure_bundle(
                prompt=source_prompt or validated_spec.title or validated_spec.program_id or "program-spec",
                program_spec=validated_spec,
                translator_label=str(validated_spec.translator_metadata.get("translator", "program-spec")),
                timings={"compile_ns": perf_counter_ns() - compile_start_ns},
                reason="unresolvable_operator",
                notes=error_notes,
            )
            result = _persist_bundle(bundle, artifact_root)
            bundle.timings["submit_total_ns"] = perf_counter_ns() - submit_start_ns
            Path(result["artifact_path"]).write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
            result["timings"] = dict(bundle.timings)
            result["backend"] = dict(bundle.backend)
            result["program_spec"] = dict(bundle.program_spec)
            return result

    # Re-attempt final assembly
    try:
        plan = language.build_plan_from_program_spec(validated_spec)
    except ValueError as error:
        bundle = _build_program_spec_failure_bundle(
            prompt=source_prompt or validated_spec.title or validated_spec.program_id or "program-spec",
            program_spec=validated_spec,
            translator_label=str(validated_spec.translator_metadata.get("translator", "program-spec")),
            timings={"compile_ns": perf_counter_ns() - compile_start_ns},
            reason="program_spec_synthesis_failed",
            notes=str(error),
        )
        result = _persist_bundle(bundle, artifact_root)
        bundle.timings["submit_total_ns"] = perf_counter_ns() - submit_start_ns
        Path(result["artifact_path"]).write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
        result["timings"] = dict(bundle.timings)
        result["backend"] = dict(bundle.backend)
        result["program_spec"] = dict(bundle.program_spec)
        return result
    compile_ns = perf_counter_ns() - compile_start_ns
    if context is None:
        context = {}

    required_inputs = [str(item.get("name", "")) for item in validated_spec.requested_inputs if bool(item.get("required", False))]
    missing_required_inputs = [name for name in required_inputs if name not in context]

    if missing_required_inputs:
        bundle = ArtifactBundle(
            run_id=f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}",
            prompt=source_prompt or validated_spec.title or validated_spec.program_id or "program-spec",
            plan=plan,
            outputs={},
            status="created",
            reason_codes=["program_created"],
            trace=ExecutionTrace(events=[]),
            compiler={
                "translator": str(validated_spec.translator_metadata.get("translator", "program-spec")),
                "confidence": validated_spec.confidence,
                "assumptions": list(validated_spec.assumptions),
                "missing_information": list(validated_spec.missing_information),
            },
            language_snapshot=language.snapshot_for_plan(plan, []),
            timings={"compile_ns": compile_ns},
            input_contract=[dict(item) for item in validated_spec.requested_inputs],
            program_spec=validated_spec.to_dict(),
            synthesis_validation={"status": "success", "failures": []},
        )
    else:
        deployment_root = _deployment_root_for_artifact_root(artifact_root)
        skill_registry = SkillRegistry(deployment_root)
        kernel = SymKernel(skill_registry=skill_registry, language=language)
        converge_start_ns = perf_counter_ns()
        language_document = language.snapshot_for_plan(plan, [])
        convergence = kernel.replay_language(
            language_document,
            context=context,
        )
        converge_ns = perf_counter_ns() - converge_start_ns
        bundle = build_bundle(
            prompt=source_prompt or validated_spec.title or validated_spec.program_id or "program-spec",
            convergence=convergence,
            compiler_meta={
                "translator": str(validated_spec.translator_metadata.get("translator", "program-spec")),
                "confidence": validated_spec.confidence,
                "assumptions": list(validated_spec.assumptions),
                "missing_information": list(validated_spec.missing_information),
            },
            timings={**dict(convergence.timings), "compile_ns": compile_ns, "converge_ns": converge_ns},
            program_spec=validated_spec.to_dict(),
            synthesis_validation={"status": "success", "failures": []},
        )
    result = _persist_bundle(bundle, artifact_root)
    if bundle.status == "success":
        _update_skill_registry(bundle, artifact_root)
    _register_program_id(result, bundle, artifact_root)
    bundle.timings["submit_total_ns"] = perf_counter_ns() - submit_start_ns
    Path(result["artifact_path"]).write_text(json.dumps(bundle.to_dict(), indent=2), encoding="utf-8")
    result["timings"] = dict(bundle.timings)
    result["backend"] = dict(bundle.backend)
    result["program_spec"] = dict(bundle.program_spec)
    return result


def replay_language(
    language_path: str | Path,
    artifact_root: str | Path = "artifacts",
    context: dict[str, object] | None = None,
    input_payload: dict[str, object] | None = None,
) -> dict[str, object]:
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
    validated_inputs = _validate_invocation_inputs(language_document, input_payload)
    if validated_inputs:
        context = {**dict(context or {}), **validated_inputs}

    replay_kernel_start_ns = perf_counter_ns()
    deployment_root = _deployment_root_for_artifact_root(artifact_root)
    skill_registry = SkillRegistry(deployment_root)
    convergence = SymKernel(skill_registry=skill_registry, deployment_root=deployment_root).replay_language(language_document, context=context)
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
    result["input_contract"] = list(bundle.input_contract)
    return result


def replay_program_id(
    program_id: str,
    artifact_root: str | Path = "artifacts",
    context: dict[str, object] | None = None,
    input_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    deployment_root = _deployment_root_for_artifact_root(artifact_root)
    entry = ProgramRegistry(deployment_root).resolve(program_id)
    result = replay_language(
        entry["machine_code_path"],
        artifact_root=artifact_root,
        context=context,
        input_payload=input_payload,
    )
    result["program_id"] = program_id
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
    deployment_root = _deployment_root_for_artifact_root(artifact_root)
    convergence = SymKernel(deployment_root=deployment_root).replay_language(language_document, context=context)
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


def _add_translator_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--translator", choices=["heuristic", "ollama", "openai-compatible", "anthropic"], default="heuristic", help="Ingress translator to use")
    parser.add_argument("--ollama-model", help="Ollama model name for translator=ollama")
    parser.add_argument("--translator-model", help="Model name for non-heuristic translators")
    parser.add_argument("--translator-endpoint", help="Override the translator HTTP endpoint")
    parser.add_argument("--translator-api-key", help="API key for remote translator providers")
    parser.add_argument("--translator-api-key-env", help="Environment variable to read the translator API key from")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create, invoke, or explain Symkern machine artifacts.")
    subparsers = parser.add_subparsers(dest="subcommand")

    create_parser = subparsers.add_parser("create-program", help="Create a Symkern program from a prompt")
    create_source = create_parser.add_mutually_exclusive_group(required=True)
    create_source.add_argument("--prompt", help="Natural-language or symbolic prompt")
    create_source.add_argument("--program-spec-file", help="Path to a ProgramSpec JSON file")
    create_source.add_argument("--program-spec-json", help="Inline ProgramSpec JSON")
    create_parser.add_argument("--program-id", help="Stable identifier to associate with the created program")
    create_parser.add_argument("--artifact-root", default="artifacts", help="Directory for run artifacts")
    _add_translator_arguments(create_parser)

    invoke_parser = subparsers.add_parser("invoke-program", help="Invoke a previously created Symkern program")
    invoke_source = invoke_parser.add_mutually_exclusive_group(required=True)
    invoke_source.add_argument("--machine-code", help="Path to a persisted machine_code.bin or legacy machine_language.json file")
    invoke_source.add_argument("--program-id", help="Stable program identifier registered during creation")
    invoke_parser.add_argument("--artifact-root", default="artifacts", help="Directory for run artifacts")
    invoke_inputs = invoke_parser.add_mutually_exclusive_group()
    invoke_inputs.add_argument("--input-json", help="Inline JSON object to bind as invocation inputs")
    invoke_inputs.add_argument("--input-file", help="Path to a JSON file containing invocation inputs")

    explain_parser = subparsers.add_parser("explain-program", help="Explain a previously created Symkern program")
    explain_parser.add_argument("--machine-code", required=True, help="Path to a persisted machine_code.bin or legacy machine_language.json file")
    explain_parser.add_argument("--artifact-root", default="artifacts", help="Directory for run artifacts")

    export_parser = subparsers.add_parser("export-translator-context", help="Export the ProgramSpec schema and operator registry for external translators")
    export_parser.add_argument("--output", help="Optional path to write the translator context JSON")

    legacy = parser.add_argument_group("legacy flags")
    legacy_command_group = legacy.add_mutually_exclusive_group()
    legacy_command_group.add_argument("--prompt", help="Natural-language or symbolic prompt")
    legacy_command_group.add_argument("--replay-language", help="Path to a persisted machine_code.bin or legacy machine_language.json file")
    legacy_command_group.add_argument("--explain-machine-code", help="Path to a persisted machine_code.bin or legacy machine_language.json file")
    legacy.add_argument("--artifact-root", default="artifacts", help="Directory for run artifacts")
    _add_translator_arguments(legacy)
    return parser


def _print_program_result(result: dict[str, object]) -> None:
    print(f"status: {result['status']}")
    if result.get("program_id"):
        print(f"program-id: {result['program_id']}")
    print(f"machine-code: {result.get('machine_code_path')}")
    print(f"machine-symbols: {result.get('machine_symbols_path')}")
    print(f"artifact: {result['artifact_path']}")
    print(f"periscope: {result['periscope_path']}")
    print(result["plan_view"])


def _run_create_command(args: argparse.Namespace) -> int:
    if getattr(args, "program_spec_file", None) or getattr(args, "program_spec_json", None):
        result = submit_program_spec(
            _load_program_spec_payload(getattr(args, "program_spec_file", None), getattr(args, "program_spec_json", None)),
            artifact_root=args.artifact_root,
            program_id=getattr(args, "program_id", None),
        )
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
            program_id=getattr(args, "program_id", None),
        )
    _print_program_result(result)
    return 0


def _run_invoke_command(args: argparse.Namespace) -> int:
    if getattr(args, "program_id", None):
        result = replay_program_id(
            args.program_id,
            artifact_root=args.artifact_root,
            input_payload=_load_input_payload(getattr(args, "input_json", None), getattr(args, "input_file", None)),
        )
        print(f"source-program: {result['program_id']}")
    else:
        result = replay_language(
            args.machine_code,
            artifact_root=args.artifact_root,
            input_payload=_load_input_payload(getattr(args, "input_json", None), getattr(args, "input_file", None)),
        )
        print(f"source-language: {result['source_language_path']}")
    _print_program_result(result)
    return 0


def _run_explain_command(args: argparse.Namespace) -> int:
    result = explain_machine_code(args.machine_code, artifact_root=args.artifact_root)
    print(f"source-language: {result['source_language_path']}")
    print(f"status: {result['status']}")
    print(f"periscope: {result['periscope_path']}")
    return 0


def _run_export_context_command(args: argparse.Namespace) -> int:
    context_bundle = build_translator_context_bundle()
    rendered = json.dumps(context_bundle, indent=2)
    if getattr(args, "output", None):
        Path(args.output).write_text(rendered, encoding="utf-8")
        print(f"translator-context: {args.output}")
    else:
        print(rendered)
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.subcommand == "create-program":
        raise SystemExit(_run_create_command(args))
    if args.subcommand == "invoke-program":
        raise SystemExit(_run_invoke_command(args))
    if args.subcommand == "explain-program":
        raise SystemExit(_run_explain_command(args))
    if args.subcommand == "export-translator-context":
        raise SystemExit(_run_export_context_command(args))

    if args.explain_machine_code:
        raise SystemExit(_run_explain_command(argparse.Namespace(machine_code=args.explain_machine_code, artifact_root=args.artifact_root)))
    if args.replay_language:
        raise SystemExit(_run_invoke_command(argparse.Namespace(machine_code=args.replay_language, artifact_root=args.artifact_root)))
    if args.prompt:
        raise SystemExit(_run_create_command(args))
    parser.error("either a subcommand or one legacy command flag is required")


if __name__ == "__main__":
    main()
