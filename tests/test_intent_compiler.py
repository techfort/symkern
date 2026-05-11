from symkern.intent_compiler import IntentCompiler
from symkern.prompt_layer import PROGRAM_SPEC_VERSION


def test_compiler_normalizes_symbolic_prompt() -> None:
    compiler = IntentCompiler()
    result = compiler.compile("→Ω detect stream anomalies\nΔ minimize_false_positives\n⟐ artifact_store")

    assert result.translator == "symbolic"
    assert result.intent.goals == ["detect stream anomalies"]
    assert result.intent.constraints == ["minimize_false_positives"]
    assert result.intent.sinks == ["artifact_store"]


def test_compiler_recognizes_gaussian_array_statistics_prompt() -> None:
    compiler = IntentCompiler()

    result = compiler.compile(
        "Make up an array of 20 numbers with random numbers between 0-20 following a gaussian distribution. Produce the standard deviation, mean and median."
    )

    assert result.intent.goals == ["generate_gaussian_array_statistics"]
    assert result.intent.state["length"] == 20
    assert result.intent.state["min_value"] == 0
    assert result.intent.state["max_value"] == 20
    assert result.intent.state["distribution"] == "gaussian"
    assert result.intent.state["requested_statistics"] == ["standard_deviation", "mean", "median"]
    assert result.program_spec.spec_version == PROGRAM_SPEC_VERSION
    assert result.program_spec.program_id == "generate-gaussian-array-statistics"
    assert result.program_spec.requested_inputs[0]["name"] == "source_array"
    assert result.program_spec.requested_outputs[1]["name"] == "statistics"
    assert result.program_spec.transformations[1]["stage_id"] == "compute_statistics"


def test_compiler_preserves_unresolved_program_request_in_program_spec() -> None:
    compiler = IntentCompiler()

    result = compiler.compile("Generate a decimal sequence, map square roots, then sum the result.")

    assert result.intent.missing_information == ["No domain-specific planner matched the prompt; using generic plan synthesis."]
    assert result.program_spec.transformations[0]["kind"] == "unresolved_goal"
    assert result.program_spec.synthesis_gaps[0]["reason"] == "unsupported_goal_family"
    assert result.program_spec.requested_outputs[0]["name"] == "emitted"
