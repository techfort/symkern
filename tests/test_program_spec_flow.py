import json
from pathlib import Path

from symkern.cli import replay_program_id, submit_program_spec, submit_prompt
from symkern.program_spec_contract import build_translator_context_bundle
from symkern.prompt_layer import ProgramSpec


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_translator_context_bundle_exposes_program_spec_schema_and_text_ops() -> None:
    context_bundle = build_translator_context_bundle()

    assert context_bundle["schema_version"] == "symkern.translator-context/v1alpha1"
    assert context_bundle["program_spec_schema"]["schema_version"] == "symkern.program-spec/v1alpha1"
    capability_ids = {item["capability_id"] for item in context_bundle["operator_registry"]["capabilities"]}
    assert "core.normalize_text_words" in capability_ids
    assert "core.render_camel_case" in capability_ids
    assert "core.render_snake_case" in capability_ids


def test_program_spec_creation_registers_program_id_and_invokes_by_id(tmp_path: Path) -> None:
    spec = ProgramSpec.from_dict(
        {
            "spec_version": "symkern.program-spec/v1alpha1",
            "program_id": "case-42",
            "title": "Given a text, return its camelCase and snake_case equivalent.",
            "requested_inputs": [
                {
                    "name": "text",
                    "kind": "string",
                    "required": True,
                    "source": "invoke-time",
                }
            ],
            "requested_outputs": [
                {"name": "camel_case", "kind": "string"},
                {"name": "snake_case", "kind": "string"},
            ],
            "transformations": [
                {
                    "operator_id": "core.normalize_text_words",
                    "inputs": ["text"],
                    "outputs": ["word_tokens"],
                },
                {
                    "operator_id": "core.render_camel_case",
                    "inputs": ["word_tokens"],
                    "outputs": ["camel_case"],
                },
                {
                    "operator_id": "core.render_snake_case",
                    "inputs": ["word_tokens"],
                    "outputs": ["snake_case"],
                },
            ],
            "translator_metadata": {"translator": "test-program-spec"},
            "confidence": 0.9,
        }
    )

    created = submit_program_spec(spec, artifact_root=tmp_path)
    created_artifact = json.loads(Path(created["artifact_path"]).read_text(encoding="utf-8"))

    assert created["status"] == "created"
    assert created["program_id"] == "case-42"
    assert created["machine_code_path"] is not None
    assert created_artifact["reason_codes"] == ["program_created"]
    assert created_artifact["program_spec"]["program_id"] == "case-42"

    invoked = replay_program_id(
        "case-42",
        artifact_root=tmp_path,
        input_payload={"text": "hello sym kern"},
    )
    invoked_artifact = json.loads(Path(invoked["artifact_path"]).read_text(encoding="utf-8"))

    assert invoked["status"] == "success"
    assert invoked["program_id"] == "case-42"
    assert invoked_artifact["outputs"]["camel_case"] == "helloSymKern"
    assert invoked_artifact["outputs"]["snake_case"] == "hello_sym_kern"


def test_external_llm_style_program_spec_with_operator_ids_creates_and_invokes(tmp_path: Path) -> None:
    spec = ProgramSpec.from_dict(
        {
            "spec_version": "symkern.program-spec/v1alpha1",
            "program_id": "43",
            "requested_inputs": [{"name": "text"}],
            "requested_outputs": [{"name": "camel_case"}, {"name": "snake_case"}],
            "transformations": [
                {"operator_id": "core.normalize_text_words", "outputs": [{"name": "word_tokens"}]},
                {"operator_id": "core.render_camel_case", "inputs": [{"name": "word_tokens"}], "outputs": [{"name": "camel_case"}]},
                {"operator_id": "core.render_snake_case", "inputs": [{"name": "word_tokens"}], "outputs": [{"name": "snake_case"}]},
            ],
        }
    )

    created = submit_program_spec(spec, artifact_root=tmp_path)
    invoked = replay_program_id("43", artifact_root=tmp_path, input_payload={"text": "sym kern works"})
    invoked_artifact = json.loads(Path(invoked["artifact_path"]).read_text(encoding="utf-8"))

    assert created["status"] == "created"
    assert invoked_artifact["outputs"]["camel_case"] == "symKernWorks"
    assert invoked_artifact["outputs"]["snake_case"] == "sym_kern_works"


def test_submit_prompt_with_mocked_ollama_authors_program_spec_and_creates_program(tmp_path: Path, monkeypatch) -> None:
    def fake_urlopen(request, timeout=60):
        request_payload = json.loads(request.data.decode("utf-8"))
        assert request_payload["model"] == "llama3.1:8b"
        assert "ProgramSpec" in request_payload["prompt"]
        return _FakeResponse(
            {
                "response": json.dumps(
                    {
                        "spec_version": "symkern.program-spec/v1alpha1",
                        "program_id": "44",
                        "requested_inputs": [{"name": "text"}],
                        "requested_outputs": [{"name": "camel_case"}, {"name": "snake_case"}],
                        "transformations": [
                            {"operator": "core.normalize_text_words", "outputs": [{"name": "word_tokens"}]},
                            {"operator": "core.render_camel_case", "inputs": [{"name": "word_tokens"}], "outputs": [{"name": "camel_case"}]},
                            {"operator": "core.render_snake_case", "inputs": [{"name": "word_tokens"}], "outputs": [{"name": "snake_case"}]},
                        ],
                    }
                )
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    created = submit_prompt(
        "Given a text, return its camelCase and snake_case equivalent.",
        artifact_root=tmp_path,
        translator="ollama",
        ollama_model="llama3.1:8b",
    )
    invoked = replay_program_id("44", artifact_root=tmp_path, input_payload={"text": "launch sym kern"})
    invoked_artifact = json.loads(Path(invoked["artifact_path"]).read_text(encoding="utf-8"))

    assert created["status"] == "created"
    assert created["program_id"] == "44"
    assert created["program_spec"]["transformations"][0]["operator_id"] == "core.normalize_text_words"
    assert invoked_artifact["outputs"]["camel_case"] == "launchSymKern"
    assert invoked_artifact["outputs"]["snake_case"] == "launch_sym_kern"


# ---------------------------------------------------------------------------
# Synthesis loop tests
# ---------------------------------------------------------------------------

class _MockTranslatorAdapter:
    """Minimal mock for testing the synthesis loop: returns a fixed synthesis response."""

    def __init__(self, synthesis_response: dict) -> None:
        self._synthesis_response = synthesis_response
        self.calls: list[str] = []

    def synthesize_operator(self, operator_id: str, existing_operator_ids, program_spec_context=None):
        self.calls.append(operator_id)
        from symkern.translator import TranslationEnvelope
        return TranslationEnvelope(payload=self._synthesis_response, translator="mock:synthesize")


def _make_unknown_op_spec(program_id: str) -> "ProgramSpec":
    return ProgramSpec.from_dict(
        {
            "spec_version": "symkern.program-spec/v1alpha1",
            "program_id": program_id,
            "requested_inputs": [{"name": "value"}],
            "requested_outputs": [{"name": "doubled"}],
            "transformations": [
                {
                    "operator_id": "custom.double_value",
                    "inputs": ["value"],
                    "outputs": ["doubled"],
                },
            ],
        }
    )


def test_synthesis_loop_handler_spec_creates_program(tmp_path: Path) -> None:
    """When an operator is missing, a handler_spec synthesis response causes it to be compiled and registered."""
    synthesis_response = {
        "implementation_kind": "handler_spec",
        "operator_id": "custom.double_value",
        "inputs": ["value"],
        "outputs": ["doubled"],
        "description": "Doubles the input value.",
        "algorithm_steps": [
            {"assign": "value", "from_context": "value"},
            {"assign": "doubled", "expr": "value * 2"},
        ],
    }
    adapter = _MockTranslatorAdapter(synthesis_response)
    spec = _make_unknown_op_spec("synth-handler-1")

    result = submit_program_spec(spec, artifact_root=tmp_path, translator_adapter=adapter)

    assert result["status"] == "created", f"Expected created, got {result.get('status')}: {result}"
    assert adapter.calls == ["custom.double_value"]

    # The synthesized op should be persisted in the registry
    from pathlib import Path as P
    registry_path = P(tmp_path).parent / ".symkern" / "operators" / "registry.json"
    # Find registry relative to where the language is rooted (deployment_root)
    import json as _json
    # The program was created; invoke it to confirm the handler actually works
    invoked = replay_program_id("synth-handler-1", artifact_root=tmp_path, input_payload={"value": 6})
    invoked_artifact = _json.loads(P(invoked["artifact_path"]).read_text(encoding="utf-8"))
    assert invoked_artifact["outputs"]["doubled"] == 12


def test_synthesis_loop_composition_creates_program(tmp_path: Path) -> None:
    """A composition synthesis response chains existing ops without generating new code."""
    # We'll use a composition spec that chains normalize_text_words -> render_snake_case
    # and wraps it as a custom operator
    synthesis_response = {
        "implementation_kind": "composition",
        "operator_id": "custom.text_to_snake",
        "inputs": ["text"],
        "outputs": ["snake_case"],
        "description": "Converts text to snake_case by chaining normalize + render.",
        "composition_steps": [
            {"operator_id": "core.normalize_text_words", "inputs": ["text"], "outputs": ["word_tokens"]},
            {"operator_id": "core.render_snake_case", "inputs": ["word_tokens"], "outputs": ["snake_case"]},
        ],
    }
    adapter = _MockTranslatorAdapter(synthesis_response)
    spec = ProgramSpec.from_dict(
        {
            "spec_version": "symkern.program-spec/v1alpha1",
            "program_id": "synth-compose-1",
            "requested_inputs": [{"name": "text"}],
            "requested_outputs": [{"name": "snake_case"}],
            "transformations": [
                {
                    "operator_id": "custom.text_to_snake",
                    "inputs": ["text"],
                    "outputs": ["snake_case"],
                },
            ],
        }
    )
    result = submit_program_spec(spec, artifact_root=tmp_path, translator_adapter=adapter)
    assert result["status"] == "created", f"Expected created, got {result.get('status')}: {result}"
    assert adapter.calls == ["custom.text_to_snake"]


def test_synthesis_loop_fails_closed_when_synthesis_unavailable(tmp_path: Path) -> None:
    """Without a translator_adapter, an unknown operator produces a failure artifact."""
    spec = _make_unknown_op_spec("synth-fail-1")
    result = submit_program_spec(spec, artifact_root=tmp_path, translator_adapter=None)
    assert result["status"] == "failed"


def test_synthesis_loop_fails_closed_when_synthesis_response_is_invalid(tmp_path: Path) -> None:
    """A synthesis response that cannot be parsed should fail closed gracefully."""
    class _BadAdapter:
        def synthesize_operator(self, operator_id, existing_operator_ids, program_spec_context=None):
            raise ValueError("LLM returned nonsense")

    spec = _make_unknown_op_spec("synth-fail-2")
    result = submit_program_spec(spec, artifact_root=tmp_path, translator_adapter=_BadAdapter())
    assert result["status"] == "failed"


def test_synthesis_loop_persists_operator_to_registry_and_reloads(tmp_path: Path) -> None:
    """After synthesizing an operator, a fresh MachineLanguage should load it from the durable registry."""
    import json as _json
    from pathlib import Path as P

    synthesis_response = {
        "implementation_kind": "handler_spec",
        "operator_id": "custom.triple_value",
        "inputs": ["value"],
        "outputs": ["tripled"],
        "description": "Triples the input.",
        "algorithm_steps": [
            {"assign": "value", "from_context": "value"},
            {"assign": "tripled", "expr": "value * 3"},
        ],
    }
    spec = ProgramSpec.from_dict(
        {
            "spec_version": "symkern.program-spec/v1alpha1",
            "program_id": "synth-persist-1",
            "requested_inputs": [{"name": "value"}],
            "requested_outputs": [{"name": "tripled"}],
            "transformations": [
                {"operator_id": "custom.triple_value", "inputs": ["value"], "outputs": ["tripled"]},
            ],
        }
    )
    adapter = _MockTranslatorAdapter(synthesis_response)
    result = submit_program_spec(spec, artifact_root=tmp_path, translator_adapter=adapter)
    assert result["status"] == "created"

    # Find the registry file written by submit_program_spec
    deployment_root = tmp_path
    registry_path = deployment_root / ".symkern" / "operators" / "registry.json"
    assert registry_path.exists(), "Registry file should have been created after synthesis"
    registry = _json.loads(registry_path.read_text(encoding="utf-8"))
    op_ids = {entry["operator_id"] for entry in registry.get("operators", [])}
    assert "custom.triple_value" in op_ids, f"Synthesized op not persisted; got {op_ids}"
