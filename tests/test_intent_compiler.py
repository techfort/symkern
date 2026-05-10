from symkern.intent_compiler import IntentCompiler


def test_compiler_normalizes_symbolic_prompt() -> None:
    compiler = IntentCompiler()
    result = compiler.compile("→Ω detect stream anomalies\nΔ minimize_false_positives\n⟐ artifact_store")

    assert result.translator == "symbolic"
    assert result.intent.goals == ["detect stream anomalies"]
    assert result.intent.constraints == ["minimize_false_positives"]
    assert result.intent.sinks == ["artifact_store"]
