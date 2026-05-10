from pathlib import Path

from symkern.artifacts import ArtifactBundle, ArtifactStore
from symkern.cli import explain_machine_code, replay_language, submit_prompt
from symkern.kernel import SymKernel
from symkern.logging import ExecutionTrace
from symkern.machine_code import CODE_MAGIC, LEXICON_MAGIC, SYMBOLS_MAGIC
from symkern.nodes import PlanGraph
from symkern.prompt_layer import PromptIntent
from symkern.streaming import synthetic_anomaly_stream


def test_artifact_store_round_trip(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    bundle = ArtifactBundle(
        run_id="run-test",
        prompt="test prompt",
        plan=PlanGraph(plan_id="plan", metadata={"goals": ["test"]}),
        outputs={"emitted": {"message": "ok"}},
        status="success",
        trace=ExecutionTrace(),
    )

    code_path, dictionary_path = store.save_machine_code(bundle)
    path = store.save_machine_artifact(bundle)
    machine_language = store.load_machine_language(code_path, dictionary_path)
    loaded = store.load_machine_artifact(path)

    assert code_path.read_bytes().startswith(CODE_MAGIC)
    assert dictionary_path.read_bytes().startswith(SYMBOLS_MAGIC)
    assert store.lexicon_path().read_bytes().startswith(LEXICON_MAGIC)
    assert machine_language["plan"]["plan_id"] == "plan"
    assert machine_language["schema_version"] == "symkern.machine-language/v1alpha1"
    assert machine_language["plan"]["nodes"] == []
    assert loaded["run_id"] == "run-test"
    assert loaded["status"] == "success"
    assert loaded["timings"] == {}


def test_machine_language_can_be_replayed(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    bundle = ArtifactBundle(
        run_id="run-replay",
        prompt="replay prompt",
        plan=PlanGraph.from_dict(
            {
                "plan_id": "plan-default",
                "nodes": [
                    {
                        "node_id": "n1",
                        "op_id": "core.generate_random_array",
                        "outputs": ["source_array"],
                        "metadata": {"length": 5, "min_value": 1, "max_value": 10},
                    },
                    {
                        "node_id": "n2",
                        "op_id": "core.random_math_map",
                        "inputs": ["source_array"],
                        "outputs": ["mapped_array", "operations"],
                        "metadata": {"operation_pool": ["add", "subtract", "multiply"]},
                    },
                    {
                        "node_id": "n3",
                        "op_id": "core.emit_sink",
                        "inputs": ["mapped_array", "operations", "source_array"],
                        "outputs": ["emitted"],
                        "metadata": {"sinks": ["artifact_store"], "emission_kind": "array_map"},
                    },
                ],
                "edges": [["n1", "n2"], ["n1", "n3"], ["n2", "n3"]],
                "state_bindings": {},
                "metadata": {"goals": ["generate_random_mapped_array"]},
            }
        ),
        outputs={},
        status="success",
        trace=ExecutionTrace(),
        language_snapshot={
            "kind": "symkern.machine_language",
            "schema_version": "symkern.machine-language/v1alpha1",
            "plan": {
                "plan_id": "plan-default",
                "nodes": [
                    {
                        "node_id": "n1",
                        "op_code": 201,
                        "inputs": [],
                        "outputs": ["source_array"],
                        "execution_mode": "bulk",
                        "metadata": {"length": 5, "min_value": 1, "max_value": 10},
                        "provenance": {},
                        "state_refs": [],
                        "valid": True,
                    },
                    {
                        "node_id": "n2",
                        "op_code": 202,
                        "inputs": ["source_array"],
                        "outputs": ["mapped_array", "operations"],
                        "execution_mode": "bulk",
                        "metadata": {"operation_pool": ["add", "subtract", "multiply"]},
                        "provenance": {},
                        "state_refs": [],
                        "valid": True,
                    },
                    {
                        "node_id": "n3",
                        "op_code": 105,
                        "inputs": ["mapped_array", "operations", "source_array"],
                        "outputs": ["emitted"],
                        "execution_mode": "bulk",
                        "metadata": {"sinks": ["artifact_store"], "emission_kind": "array_map"},
                        "provenance": {},
                        "state_refs": [],
                        "valid": True,
                    },
                ],
                "edges": [["n1", "n2"], ["n1", "n3"], ["n2", "n3"]],
                "state_bindings": {},
                "metadata": {"goals": ["generate_random_mapped_array"]},
            },
            "operation_schemas": {
                "core.emit_sink": {
                    "op_code": 105,
                    "signature": {"inputs": ["detections"], "outputs": ["emitted"]},
                    "machine_metadata": {"category": "sink"},
                    "description": "Emit final detections to the configured sink.",
                },
                "core.generate_random_array": {
                    "op_code": 201,
                    "signature": {"inputs": [], "outputs": ["source_array"]},
                    "machine_metadata": {"category": "array"},
                    "description": "Generate a bounded random integer array.",
                },
                "core.random_math_map": {
                    "op_code": 202,
                    "signature": {"inputs": ["source_array"], "outputs": ["mapped_array", "operations"]},
                    "machine_metadata": {"category": "array"},
                    "description": "Apply randomized math operations to each array element.",
                },
            },
            "inventions": [],
        },
    )

    code_path, dictionary_path = store.save_machine_code(bundle)
    replay_result = SymKernel().replay_language(store.load_machine_language(code_path, dictionary_path))
    replayed_language = store.load_machine_language(code_path, dictionary_path)

    assert replay_result.status == "success"
    assert replay_result.outputs["source_array"] == [9, 7, 5, 6, 5]
    assert replay_result.outputs["mapped_array"] == [10, 14, 4, 8, 10]
    assert "op_id" not in replayed_language["plan"]["nodes"][0]
    assert "op_id" not in next(iter(replayed_language["operation_schemas"].values()))
    assert "source_ops" not in replayed_language["inventions"][0] if replayed_language["inventions"] else True


def test_live_language_snapshot_does_not_persist_symbolic_operation_names() -> None:
    intent = PromptIntent(
        goals=["detect_stream_anomalies"],
        constraints=["minimize_false_positives", "low_latency"],
        sinks=["artifact_store"],
    )

    result = SymKernel().run(intent, context={"events": synthetic_anomaly_stream()}, strategy="conservative")
    snapshot = result.language_snapshot

    assert all(node.op_id == "" for node in result.plan.nodes)
    assert all("op_id" not in node for node in snapshot["plan"]["nodes"])
    assert all("op_id" not in descriptor for descriptor in snapshot["operation_schemas"].values())
    assert all("op_id" not in invention for invention in snapshot["inventions"])
    assert all("source_ops" not in invention for invention in snapshot["inventions"])
    assert all(isinstance(item, int) for item in snapshot["plan"]["metadata"].get("rewrites_applied", []))


def test_machine_language_can_be_replayed_via_cli(tmp_path: Path) -> None:
    submitted = submit_prompt(
        "Create a 5-element array of random numbers whose value is between 1 and 10, then create an array that is a map of the first array with random maths operation applied to the members of the first array.",
        artifact_root=tmp_path,
    )

    replayed = replay_language(submitted["language_path"], artifact_root=tmp_path)
    assert replayed["status"] == "success"
    assert Path(replayed["artifact_path"]).exists()
    assert Path(replayed["periscope_path"]).exists()
    assert Path(replayed["machine_code_path"]).read_bytes().startswith(CODE_MAGIC)
    assert Path(replayed["machine_symbols_path"]).read_bytes().startswith(SYMBOLS_MAGIC)


def test_machine_code_explain_command_writes_periscope_without_exposing_symbols(tmp_path: Path) -> None:
    submitted = submit_prompt(
        "Detect anomalies in a streaming signal with low false positives and low latency",
        artifact_root=tmp_path,
    )

    explained = explain_machine_code(submitted["machine_code_path"], artifact_root=tmp_path)
    periscope_text = Path(explained["periscope_path"]).read_text(encoding="utf-8")

    assert explained["status"] == "success"
    assert Path(explained["periscope_path"]).exists()
    assert "Periscope" in periscope_text
    assert "detect_stream_anomalies" in periscope_text
    assert "opcode 1000" in periscope_text
    assert "## Reconstructed Strategy" in periscope_text
    assert "## Machine Intent Narrative" in periscope_text
    assert "## Machine Abstractions" in periscope_text
    assert "## Performance" in periscope_text
    assert "compresses source opcodes" in periscope_text
    assert "conservative anomaly envelope" in periscope_text
    assert "fused scoring and threshold comparison" in periscope_text
    assert "Executed opcode 1000." in periscope_text
    assert "kernel_total_ns:" in periscope_text
    assert "Per-node execution:" in periscope_text
    assert "## Inputs" in periscope_text
    assert "Passed input `events` enters from outside the machine plan." in periscope_text
    assert "## Outputs" in periscope_text
    assert "Output `emitted` =" in periscope_text


def test_machine_code_explain_command_includes_synthesized_inputs_and_outputs_for_array_runs(tmp_path: Path) -> None:
    submitted = submit_prompt(
        "Create a 5-element array of random numbers whose value is between 1 and 10, then create an array that is a map of the first array with random maths operation applied to the members of the first array.",
        artifact_root=tmp_path,
    )

    explained = explain_machine_code(submitted["machine_code_path"], artifact_root=tmp_path)
    periscope_text = Path(explained["periscope_path"]).read_text(encoding="utf-8")

    assert explained["status"] == "success"
    assert "## Inputs" in periscope_text
    assert "Synthesized input `source_array` was created inside the plan before downstream use." in periscope_text
    assert "## Outputs" in periscope_text
    assert "## Performance" in periscope_text
    assert "Output `source_array` = [9, 7, 5, 6, 5]" in periscope_text
    assert "Output `mapped_array` = [10, 14, 4, 8, 10]" in periscope_text


def test_submitted_artifact_persists_timings(tmp_path: Path) -> None:
    submitted = submit_prompt(
        "Make up an array of 20 numbers with random numbers between 0-20 following a gaussian distribution. Produce the standard deviation, mean and median.",
        artifact_root=tmp_path,
    )

    artifact = ArtifactStore(tmp_path).load_machine_artifact(submitted["artifact_path"])

    assert "timings" in artifact
    assert artifact["timings"]["compile_ns"] > 0
    assert artifact["timings"]["converge_ns"] > 0
    assert artifact["timings"]["execute_ns"] > 0
    assert artifact["timings"]["persist_periscope_render_ns"] > 0
    assert artifact["timings"]["persist_total_ns"] > 0
    assert artifact["timings"]["submit_total_ns"] > 0
    assert set(artifact["timings"]["node_execute_ns"].keys()) == {"n1", "n2", "n3"}
