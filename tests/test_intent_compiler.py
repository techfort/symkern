from symkern.intent_compiler import IntentCompiler


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
