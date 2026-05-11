import json

from symkern.intent_compiler import IntentCompiler
from symkern.intent_contract import SCHEMA_VERSION, SymkernIntentContract, load_intent_ontology, load_intent_schema
from symkern.prompt_layer import PromptValidator
from symkern.translator import AnthropicTranslatorAdapter, OllamaTranslatorAdapter, OpenAICompatibleTranslatorAdapter, TranslatorAdapter


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _RepairingAdapter(TranslatorAdapter):
    def translate(self, prompt: str):
        return type("Envelope", (), {"payload": {"schema_version": SCHEMA_VERSION, "goals": [], "constraints": [], "preferences": [], "state": {}, "sinks": [], "assumptions": [], "missing_information": [], "confidence": 0.4}, "translator": "repairing:test"})()

    def repair(self, prompt: str, invalid_payload: dict[str, object] | None, error_message: str):
        assert "at least one goal" in error_message
        return type(
            "Envelope",
            (),
            {
                "payload": {
                    "schema_version": SCHEMA_VERSION,
                    "goals": ["detect_stream_anomalies"],
                    "constraints": ["low false positives"],
                    "preferences": [],
                    "state": {"window_size": 5},
                    "sinks": ["console"],
                    "assumptions": ["repair path used"],
                    "missing_information": [],
                    "confidence": 0.66,
                },
                "translator": "repairing:test:repair",
            },
        )()


class _MismatchingAdapter(TranslatorAdapter):
    def translate(self, prompt: str):
        return type(
            "Envelope",
            (),
            {
                "payload": {
                    "schema_version": SCHEMA_VERSION,
                    "goals": ["generate_gaussian_array_statistics"],
                    "constraints": [],
                    "preferences": [],
                    "state": {
                        "length": 10,
                        "min_value": 1,
                        "max_value": 10,
                        "distribution": "gaussian",
                        "requested_statistics": ["standard_deviation", "mean", "median"],
                    },
                    "sinks": ["stdout"],
                    "assumptions": [],
                    "missing_information": [],
                    "confidence": 0.81,
                },
                "translator": "mismatch:test",
            },
        )()


def test_intent_contract_normalizes_constraint_and_sink_synonyms() -> None:
    contract = SymkernIntentContract(PromptValidator())

    intent = contract.normalize(
        {
            "schema_version": SCHEMA_VERSION,
            "goals": ["detect_stream_anomalies"],
            "constraints": ["low false positives", "real-time"],
            "preferences": [],
            "state": {"window_size": 5},
            "sinks": ["artifact", "console"],
            "assumptions": ["adapter test"],
            "missing_information": [],
            "confidence": 0.81,
        }
    )

    assert intent.constraints == ["minimize_false_positives", "low_latency"]
    assert intent.sinks == ["artifact_store", "stdout"]


def test_compiler_can_use_mocked_ollama_adapter(monkeypatch) -> None:
    def fake_urlopen(request, timeout=60):
        request_payload = json.loads(request.data.decode("utf-8"))
        assert request_payload["model"] == "llama3.2:3b"
        assert request_payload["format"] == "json"
        return _FakeResponse(
            {
                "response": json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "goals": ["generate_gaussian_array_statistics"],
                        "constraints": [],
                        "preferences": [],
                        "state": {
                            "length": 20,
                            "min_value": 0,
                            "max_value": 20,
                            "distribution": "gaussian",
                            "requested_statistics": ["standard_deviation", "mean", "median"],
                        },
                        "sinks": ["artifact_store", "stdout"],
                        "assumptions": ["mocked ollama output"],
                        "missing_information": [],
                        "confidence": 0.77,
                    }
                )
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    compiler = IntentCompiler(translator_adapter=OllamaTranslatorAdapter(model="llama3.2:3b"))
    result = compiler.compile(
        "Make up an array of 20 numbers with random numbers between 0-20 following a gaussian distribution. Produce the standard deviation, mean and median."
    )

    assert result.translator == "ollama:llama3.2:3b"
    assert result.intent.goals == ["generate_gaussian_array_statistics"]
    assert result.intent.state["distribution"] == "gaussian"
    assert result.confidence == 0.77


def test_compiler_repairs_invalid_translator_output() -> None:
    compiler = IntentCompiler(translator_adapter=_RepairingAdapter())

    result = compiler.compile("Detect anomalies in a streaming signal with low false positives")

    assert result.translator == "repairing:test:repair"
    assert result.intent.goals == ["detect_stream_anomalies"]
    assert result.intent.constraints == ["minimize_false_positives"]
    assert result.intent.sinks == ["stdout"]


def test_compiler_marks_translator_goal_mismatch_as_blocking_program_gap() -> None:
    compiler = IntentCompiler(translator_adapter=_MismatchingAdapter())

    result = compiler.compile("Generate a decimal sequence from 1 to 10, map the square root of each element, then sum the transformed values.")

    assert result.intent.goals == ["generate_gaussian_array_statistics"]
    assert result.program_spec.synthesis_gaps[0]["reason"] == "translator_goal_mismatch"
    assert result.program_spec.synthesis_gaps[0]["severity"] == "blocking"


def test_contract_rejects_embedded_object_strings_in_goals() -> None:
    contract = SymkernIntentContract(PromptValidator())

    try:
        contract.normalize(
            {
                "schema_version": SCHEMA_VERSION,
                "goals": ["{'goal': 'generate_gaussian_array_statistics'}"],
                "constraints": [],
                "preferences": [],
                "state": {},
                "sinks": ["stdout"],
                "assumptions": [],
                "missing_information": [],
                "confidence": 0.5,
            }
        )
    except ValueError as error:
        assert "plain strings" in str(error)
    else:
        raise AssertionError("Expected embedded object-like goal string to be rejected")


def test_build_translation_instructions_warns_against_object_like_list_items() -> None:
    from symkern.intent_contract import build_translation_instructions

    instructions = build_translation_instructions()

    assert "Every list field must contain plain strings only" in instructions
    assert "Do not serialize Python dictionaries or lists as strings" in instructions


def test_openai_compatible_adapter_uses_chat_completions(monkeypatch) -> None:
    def fake_urlopen(request, timeout=60):
        request_payload = json.loads(request.data.decode("utf-8"))
        assert request_payload["model"] == "gpt-test"
        assert request.headers["Authorization"] == "Bearer secret"
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "schema_version": SCHEMA_VERSION,
                                    "goals": ["detect_stream_anomalies"],
                                    "constraints": ["real-time"],
                                    "preferences": [],
                                    "state": {"window_size": 5},
                                    "sinks": ["artifact_store"],
                                    "assumptions": ["openai-compatible test"],
                                    "missing_information": [],
                                    "confidence": 0.71,
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    compiler = IntentCompiler(translator_adapter=OpenAICompatibleTranslatorAdapter(model="gpt-test", api_key="secret"))

    result = compiler.compile("Detect anomalies in a streaming signal with low false positives")

    assert result.translator == "openai-compatible:gpt-test"
    assert result.intent.goals == ["detect_stream_anomalies"]
    assert result.intent.constraints == ["low_latency"]


def test_anthropic_adapter_uses_messages_api(monkeypatch) -> None:
    def fake_urlopen(request, timeout=60):
        request_payload = json.loads(request.data.decode("utf-8"))
        assert request_payload["model"] == "claude-test"
        assert request.get_header("X-api-key") == "secret"
        return _FakeResponse(
            {
                "content": [
                    {
                        "text": json.dumps(
                            {
                                "schema_version": SCHEMA_VERSION,
                                "goals": ["elect_illustrious_historical_death"],
                                "constraints": [],
                                "preferences": [],
                                "state": {"date_count": 3, "lookup_source": "wikipedia.org"},
                                "sinks": ["artifact_store", "stdout"],
                                "assumptions": ["anthropic test"],
                                "missing_information": [],
                                "confidence": 0.69,
                            }
                        )
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    compiler = IntentCompiler(translator_adapter=AnthropicTranslatorAdapter(model="claude-test", api_key="secret"))

    result = compiler.compile("make up 3 historical dates, lookup on wikipedia.org what deaths occurred on those dates and elect the most illustrious one")

    assert result.translator == "anthropic:claude-test"
    assert result.intent.goals == ["elect_illustrious_historical_death"]
    assert result.intent.state["date_count"] == 3


def test_packaged_contract_resources_are_loadable() -> None:
    schema = load_intent_schema()
    ontology = load_intent_ontology()

    assert schema["schema_version"] == SCHEMA_VERSION
    assert "goals" in schema["required"]
    assert "generate_gaussian_array_statistics" in ontology["goals"]
    assert ontology["sink_synonyms"]["console"] == "stdout"